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
    source_id = config["source_id"]
    now = datetime.now(timezone.utc).isoformat()
    field_origins = {item["canonical"]: item.get("source_field", item.get("source_fields")) for item in config["mappings"]}
    if source_id == "federal_contracts":
        ocid, release_id, date = _value(row, "procurement_id"), _value(row, "reference_number"), _value(row, "contract_date")
        buyer_name, vendor, amount, description, classification = _value(row, "buyer_name"), _value(row, "vendor_name"), _float(row, "contract_value"), _value(row, "description_en"), _value(row, "commodity_code")
        start, end = _value(row, "contract_period_start"), _value(row, "delivery_date")
    elif source_id == "canadabuys_award_notices":
        ocid = _value(row, "solicitationNumber-numeroSollicitation") or _value(row, "referenceNumber-numeroReference")
        release_id = _value(row, "contractNumber-numeroContrat") or _value(row, "referenceNumber-numeroReference")
        date = _value(row, "contractAwardDate-dateAttributionContrat") or _value(row, "publicationDate-datePublication")
        buyer_name, vendor = _value(row, "contractingEntityName-nomEntitContractante-eng"), _value(row, "supplierLegalName-nomLegalFournisseur-eng")
        amount = _float(row, "contractAmount-montantContrat")
        if amount < 0:
            amount = _float(row, "totalContractValue-valeurTotaleContrat")
        description, classification = _value(row, "awardDescription-descriptionAttribution-eng") or _value(row, "title-titre-eng"), _value(row, "unspsc-unspsc") or _value(row, "gsin-nibs")
        start, end = _value(row, "contractStartDate-contratDateDebut"), _value(row, "contractEndDate-dateFinContrat")
    else:
        ocid, release_id = _value(row, "Vendor of Record (VOR) Number"), _value(row, "Vendor of Record (VOR) Number")
        date = _value(row, "Estimated Contract Start Date")
        if parse_date(date) is None:
            date = _value(row, "Estimated Electronic Tendering Posting Date")
        buyer_name, vendor, amount, description, classification = _value(row, "Buying Organization(s)"), _value(row, "Vendor of Record (VOR) Name"), 0.0, _value(row, "Vendor of Record (VOR) Name"), "VOR"
        start, end = _value(row, "Estimated Contract Start Date"), ""
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
            "items": [{"classification": {"scheme": "GSIN" if len(classification) <= 6 else "UNSPSC", "id": classification or "UNKNOWN"}}],
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


def ingest_csv(path: Path, config_path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    config = yaml.safe_load(config_path.read_text())
    with path.open(newline="", encoding=config.get("encoding", "utf-8-sig")) as stream:
        rows = [
            row for row in csv.DictReader(stream)
            if any(value.strip() for value in row.values() if value)
            and (not config.get("required_source_field") or _value(row, config["required_source_field"]))
        ]
        releases = [_release(row, config, str(path)) for row in rows[:limit]]
    validate_releases(releases)
    return releases