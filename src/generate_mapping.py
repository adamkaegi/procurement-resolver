"""Generate and validate source mappings without an external model endpoint.

The offline generator is deliberately conservative: it proposes a mapping only
when a canonical field has an obvious source-field name match and abstains
otherwise. A model adapter can replace ``propose_mapping`` later without
changing the validation gate or instrumentation contract.
"""

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .transform_registry import is_registered
from .validate import parse_date, validate_release


CANONICAL_FIELDS = [
    "ocid", "id", "date", "initiationType", "tag", "buyer.name", "buyer.id",
    "buyer.jurisdiction", "awards[].id", "awards[].date", "awards[].value.amount",
    "awards[].value.currency", "awards[].suppliers[].name", "awards[].suppliers[].id",
    "awards[].items[].classification.scheme", "awards[].items[].classification.id",
    "awards[].description", "contracts[].period.startDate", "contracts[].period.endDate",
]

FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "ocid": ("solicitationNumber-numeroSollicitation", "referenceNumber-numeroReference", "procurement_id", "Vendor of Record (VOR) Number"),
    "id": ("contractNumber-numeroContrat", "referenceNumber-numeroReference", "reference_number", "Vendor of Record (VOR) Number"),
    "date": ("contractAwardDate-dateAttributionContrat", "publicationDate-datePublication", "contract_date", "Estimated Contract Start Date"),
    "buyer.name": ("contractingEntityName-nomEntitContractante-eng", "buyer_name", "Buying Organization(s)"),
    "awards[].id": ("contractNumber-numeroContrat", "reference_number", "Vendor of Record (VOR) Number"),
    "awards[].date": ("contractAwardDate-dateAttributionContrat", "contract_date", "Estimated Contract Start Date"),
    "awards[].value.amount": ("totalContractValue-valeurTotaleContrat", "contractAmount-montantContrat", "contract_value"),
    "awards[].value.currency": ("contractCurrency-contratMonnaie",),
    "awards[].suppliers[].name": ("supplierLegalName-nomLegalFournisseur-eng", "supplierOperatingName-nomCommercialFournisseur-eng", "vendor_name", "Vendor of Record (VOR) Name"),
    "awards[].items[].classification.id": ("unspsc", "gsin-nibs", "commodity_code"),
    "awards[].description": ("tenderDescription-descriptionAppelOffres-eng", "title-titre-eng", "description_en", "Vendor of Record (VOR) Name"),
    "contracts[].period.startDate": ("contractStartDate-contratDateDebut", "contract_period_start", "Estimated Contract Start Date"),
    "contracts[].period.endDate": ("contractEndDate-dateFinContrat", "delivery_date"),
}


def _transform_for(field: str, source_field: str) -> str:
    if field.endswith("date") or field in {"date", "contracts[].period.startDate", "contracts[].period.endDate"}:
        return "parse_date_or_publication_date" if field == "date" else "parse_date"
    if field == "awards[].value.amount":
        return "parse_nonnegative_currency_with_amount_fallback"
    if field == "awards[].value.currency":
        return "default_cad"
    if field == "awards[].items[].classification.id":
        return "first_present"
    if field == "awards[].description":
        return "direct_or_title"
    if field == "awards[].suppliers[].name":
        return "direct_or_operating_name"
    return "direct_or_reference" if field in {"ocid", "id", "awards[].id"} else "direct"


def propose_mapping(source_id: str, fields: list[str]) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    for canonical in CANONICAL_FIELDS:
        hints = FIELD_HINTS.get(canonical, ())
        matches = [field for field in hints if field in fields]
        if matches:
            source_fields = matches if len(matches) > 1 else matches[0]
            item: dict[str, Any] = {
                "canonical": canonical,
                "disposition": "mapped" if len(matches) == 1 else "derived",
                "transform": _transform_for(canonical, matches[0]),
                "confidence": "high" if len(matches) == 1 else "medium",
                "reasoning": f"Matched published field name for {canonical}.",
            }
            item["source_fields" if isinstance(source_fields, list) else "source_field"] = source_fields
        else:
            item = {
                "canonical": canonical,
                "disposition": "unmapped",
                "confidence": "high",
                "reasoning": "No unambiguous source field was found; abstention is preferred to guessing.",
                "transform": "unmapped",
            }
        mappings.append(item)
    return {
        "source_id": source_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "offline-deterministic-scaffold",
        "mappings": mappings,
    }


def validate_mapping(mapping: dict[str, Any], fields: list[str]) -> list[str]:
    errors: list[str] = []
    if not mapping.get("source_id") or not isinstance(mapping.get("mappings"), list):
        errors.append("mapping requires source_id and mappings")
    seen: set[str] = set()
    for item in mapping.get("mappings", []):
        canonical = item.get("canonical")
        if canonical in seen:
            errors.append(f"duplicate canonical field: {canonical}")
        seen.add(canonical)
        if canonical not in CANONICAL_FIELDS:
            errors.append(f"unknown canonical field: {canonical}")
        if item.get("disposition") not in {"mapped", "derived", "unmapped"}:
            errors.append(f"invalid disposition for {canonical}")
        if not item.get("reasoning"):
            errors.append(f"missing reasoning for {canonical}")
        if not is_registered(item.get("transform")):
            errors.append(f"unknown transform for {canonical}: {item.get('transform')}")
        source_fields = item.get("source_fields", [item.get("source_field")])
        for source_field in source_fields:
            if source_field is not None and source_field not in fields:
                errors.append(f"unknown source field for {canonical}: {source_field}")
    missing = set(CANONICAL_FIELDS) - seen
    errors.extend(f"missing canonical field: {field}" for field in sorted(missing))
    return errors


def _contract_history_release(row: dict[str, str], mapping: dict[str, Any]) -> dict[str, Any]:
    value = row.get("totalContractValue-valeurTotaleContrat") or row.get("contractAmount-montantContrat") or "0"
    amount = float(value.replace(",", "").replace("$", "") or "0")
    award_date = parse_date(row.get("contractAwardDate-dateAttributionContrat") or row.get("publicationDate-datePublication"))
    start = parse_date(row.get("contractStartDate-contratDateDebut"))
    end = parse_date(row.get("contractEndDate-dateFinContrat"))
    identifier = row.get("contractNumber-numeroContrat") or row.get("referenceNumber-numeroReference")
    release = {
        "ocid": row.get("solicitationNumber-numeroSollicitation") or row.get("referenceNumber-numeroReference"),
        "id": identifier,
        "date": award_date,
        "initiationType": "tender",
        "tag": ["award"],
        "buyer": {"name": row.get("contractingEntityName-nomEntitContractante-eng") or "Unknown", "id": "canadabuys_contract_history:buyer", "jurisdiction": "federal"},
        "awards": [{"id": identifier, "date": award_date, "value": {"amount": amount, "currency": row.get("contractCurrency-contratMonnaie") or "CAD"}, "suppliers": [{"name": row.get("supplierLegalName-nomLegalFournisseur-eng") or row.get("supplierOperatingName-nomCommercialFournisseur-eng") or "Unknown", "id": None}], "description": row.get("tenderDescription-descriptionAppelOffres-eng") or row.get("title-titre-eng") or None, "items": [{"classification": {"scheme": "UNSPSC" if row.get("unspsc") else "GSIN", "id": row.get("unspsc") or row.get("gsin-nibs") or "UNKNOWN"}}], "contractPeriod": {"startDate": start, "endDate": end}}],
        "contracts": [{"period": {"startDate": start, "endDate": end}, "awardID": identifier}],
        "_provenance": {"source_id": mapping["source_id"], "fetched_at": datetime.now(timezone.utc).isoformat(), "mapping_version": "provisional-generated", "raw_ref": "sample", "field_origins": {}, "extraction_conf": None},
    }
    return release


def validate_sample(mapping: dict[str, Any], sample: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if mapping["source_id"] == "canadabuys_contract_history":
        for row in sample:
            errors.extend(validate_release(_contract_history_release(row, mapping)))
    return errors


def generate(source_id: str, sample_path: Path, output_path: Path, log_path: Path, encoding: str = "utf-8-sig") -> dict[str, Any]:
    started = time.perf_counter()
    with sample_path.open(newline="", encoding=encoding) as stream:
        reader = csv.DictReader(stream)
        sample = list(reader)
        fields = reader.fieldnames or []
    retries = 0
    mapping = propose_mapping(source_id, fields)
    errors = validate_mapping(mapping, fields)
    errors.extend(validate_sample(mapping, sample[:20]))
    if errors:
        retries = 1
        mapping = propose_mapping(source_id, fields)
        errors = validate_mapping(mapping, fields)
        errors.extend(validate_sample(mapping, sample[:20]))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    event = {"source_id": source_id, "model": mapping["model"], "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": elapsed_ms, "retries": retries, "validation_outcome": "passed" if not errors else "failed", "errors": errors}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as stream:
        stream.write("PROVISIONAL\n")
        stream.write(json.dumps(event) + "\n")
    if errors:
        raise ValueError("mapping validation failed: " + "; ".join(errors))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(mapping, sort_keys=False))
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()
    generate(args.source_id, args.sample, args.output, args.log, args.encoding)


if __name__ == "__main__":
    main()