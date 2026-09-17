"""Deterministic application of reviewed Phase 1 source mappings."""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .validate import parse_date, validate_releases


def _value(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _float(row: dict[str, str], key: str) -> float:
    return float(_value(row, key).replace(",", "").replace("$", "") or "0")


def _release(row: dict[str, str], config: dict[str, Any], raw_ref: str) -> dict[str, Any]:
    # Deliberately hardcoded per source_id rather than driven generically by
    # config["mappings"] (source_field/transform) -- a disclosed trade-off,
    # not an oversight. See docs/DECISIONS.md, "Phase 1 mapping.yaml is
    # documentation, not executable config", for the reasoning and the
    # human decision needed before that changes.
    source_id = config["source_id"]
    now = datetime.now(timezone.utc).isoformat()
    field_origins = {item["canonical"]: item.get("source_field", item.get("source_fields")) for item in config["mappings"]}
    scheme: str | None = None  # branches may set it; defaults to the length heuristic below
    if source_id == "federal_contracts":
        ocid = _value(row, "procurement_id")
        release_id = _value(row, "reference_number")
        date = _value(row, "contract_date")
        buyer_name = _value(row, "buyer_name")
        vendor = _value(row, "vendor_name")
        amount = _float(row, "contract_value")
        description = _value(row, "description_en")
        classification = _value(row, "commodity_code")
        start, end = _value(row, "contract_period_start"), _value(row, "delivery_date")
    elif source_id == "canadabuys_award_notices":
        ocid = _value(row, "solicitationNumber-numeroSollicitation") or _value(row, "referenceNumber-numeroReference")
        release_id = _value(row, "contractNumber-numeroContrat") or _value(row, "referenceNumber-numeroReference")
        date = _value(row, "contractAwardDate-dateAttributionContrat") or _value(row, "publicationDate-datePublication")
        buyer_name = _value(row, "contractingEntityName-nomEntitContractante-eng")
        vendor = _value(row, "supplierLegalName-nomLegalFournisseur-eng")
        amount = _float(row, "contractAmount-montantContrat")
        if amount < 0:
            amount = _float(row, "totalContractValue-valeurTotaleContrat")
        description = _value(row, "awardDescription-descriptionAttribution-eng") or _value(row, "title-titre-eng")
        classification = _value(row, "unspsc-unspsc") or _value(row, "gsin-nibs")
        start, end = _value(row, "contractStartDate-contratDateDebut"), _value(row, "contractEndDate-dateFinContrat")
    elif source_id == "canadabuys_contract_history":
        # Same publisher, same eng/fra field-naming convention as
        # canadabuys_award_notices, but a distinct dataset (full contract
        # history vs. award-notice publications) -- see source.yaml.
        ocid = _value(row, "solicitationNumber-numeroSollicitation") or _value(row, "referenceNumber-numeroReference")
        release_id = _value(row, "referenceNumber-numeroReference")
        date = _value(row, "contractAwardDate-dateAttributionContrat") or _value(row, "publicationDate-datePublication")
        buyer_name = _value(row, "contractingEntityName-nomEntitContractante-eng")
        vendor = (
            _value(row, "supplierLegalName-nomLegalFournisseur-eng")
            or _value(row, "supplierOperatingName-nomCommercialFournisseur-eng")
        )
        amount = _float(row, "contractAmount-montantContrat")
        if amount < 0:
            amount = _float(row, "totalContractValue-valeurTotaleContrat")
        description = _value(row, "tenderDescription-descriptionAppelOffres-eng") or _value(row, "title-titre-eng")
        classification = _value(row, "unspsc") or _value(row, "gsin-nibs")
        start, end = _value(row, "contractStartDate-contratDateDebut"), _value(row, "contractEndDate-dateFinContrat")
    elif source_id == "ontario_vor":
        ocid = _value(row, "Vendor of Record (VOR) Number")
        release_id = ocid
        date = _value(row, "Start Date")
        buyer_name = config.get("buyer_name", "Ontario Government")
        vendor = _value(row, "Qualified Vendor")
        amount = 0.0
        description = _value(row, "Vendor of Record (VOR) Name")
        classification = "VOR"
        scheme = "VOR"
        start, end = _value(row, "Start Date"), _value(row, "End Date")
    else:
        raise ValueError(
            f"no mapping implementation for source_id {source_id!r} -- add an "
            "explicit branch here (see docs/DECISIONS.md, hardcoded-dispatch ADR)"
        )
    if scheme is None:
        # Federal columns carry either short GSIN-style codes or long UNSPSC
        # codes in the same field; length is the discriminator available in
        # the raw data.
        scheme = "GSIN" if len(classification) <= 6 else "UNSPSC"
    release = {
        "ocid": ocid,
        "id": release_id,
        "date": parse_date(date),
        "initiationType": "tender",
        "tag": ["award"],
        "buyer": {"name": buyer_name or "Unknown", "id": f"{source_id}:buyer", "jurisdiction": config["jurisdiction"]},
        "awards": [{
            "id": release_id,
            "date": parse_date(date),
            "value": {"amount": amount, "currency": _value(row, "contractCurrency-contratMonnaie") or "CAD"},
            "suppliers": [{"name": vendor or "Unknown", "id": None}],
            "description": description or None,
            "items": [{"classification": {"scheme": scheme, "id": classification or "UNKNOWN"}}],
            "contractPeriod": {"startDate": parse_date(start), "endDate": parse_date(end)},
        }],
        "contracts": [{"period": {"startDate": parse_date(start), "endDate": parse_date(end)}, "awardID": release_id}],
        "_provenance": {
            "source_id": source_id,
            "fetched_at": now,
            "mapping_version": config["mapping_version"],
            "raw_ref": raw_ref,
            "field_origins": field_origins,
            "extraction_conf": None,
        },
    }
    return release


def _is_usable_row(row: dict[str, str], config: dict[str, Any]) -> bool:
    """False for blank rows and, when the source config names one
    (e.g. ontario_vor's VOR number), rows missing their required field --
    footer/note rows that aren't vendors (see docs/FAILURES.md #12)."""
    has_any_value = any(value.strip() for value in row.values() if value)
    required_field = config.get("required_source_field")
    return has_any_value and (not required_field or _value(row, required_field))


def ingest_csv(path: Path, config_path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    config = yaml.safe_load(config_path.read_text())
    with path.open(newline="", encoding=config.get("encoding", "utf-8-sig")) as stream:
        for _ in range(config.get("skip_rows", 0)):
            next(stream, None)
        reader = csv.DictReader(stream)
        reader.fieldnames = [field.strip() for field in (reader.fieldnames or [])]
        rows = [
            {key.strip(): value for key, value in row.items() if key is not None}
            for row in reader
            if _is_usable_row(row, config)
        ]
        releases = [_release(row, config, str(path)) for row in rows[:limit]]
    validate_releases(releases)
    return releases