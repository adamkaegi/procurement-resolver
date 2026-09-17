"""Extract Ottawa delegated-authority contract tables from text-based PDFs."""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .validate import validate_releases


DEPARTMENTS = (
    "Transit Services",
    "Infrastructure & Water Services",
    "Recreation, Cultural & Facility Services",
    "Planning, Development and Building Services",
    "Community and Social Services",
    "Emergency and Protective Services",
    "Finance and Corporate Services",
)
RECORD_START = re.compile(r"^\s*(\d+)\s+([A-Z0-9][A-Z0-9-]+(?:-[A-Z0-9]+)*)\b")
AMOUNT_VENDOR_PREFIX = re.compile(r"\$\s*([\d,]+\.\d{2})\s+(.+)$")
AMOUNT_VENDOR_SUFFIX = re.compile(r"([\d,]+\.\d{2})\s*\$\s+(.+)$")
PERIOD = re.compile(
    r"(?:period of |for the period of |for )?(January|July)\s+([0-9]{1,2}),?\s+([0-9]{4})\s+to\s+(June|December)\s+([0-9]{1,2}),?\s+([0-9]{4})",
    re.IGNORECASE,
)


def report_period(text: str, path: Path) -> tuple[str | None, str | None]:
    match = PERIOD.search(text)
    if not match:
        if "Jan-June 2024" in path.name or "January1 2024" in path.name:
            return "2024-01-01T00:00:00+00:00", "2024-06-30T23:59:59+00:00"
        if "July 1 and December 31 2024" in text or "July 1, 2024 to December 31, 2024" in text:
            return "2024-07-01T00:00:00+00:00", "2024-12-31T23:59:59+00:00"
        return None, None
    start_month, start_day, start_year, end_month, end_day, end_year = match.groups()
    start = datetime.strptime(f"{start_month} {start_day} {start_year}", "%B %d %Y").replace(tzinfo=timezone.utc)
    end = datetime.strptime(f"{end_month} {end_day} {end_year}", "%B %d %Y").replace(tzinfo=timezone.utc)
    return start.isoformat(), end.replace(hour=23, minute=59, second=59).isoformat()


def clean_text(lines: list[str]) -> str:
    return " ".join(" ".join(lines).replace("\u2010", "-").split())


def _parse_amount_vendor_rationale(flattened: str) -> tuple[re.Match, float, str, str | None] | None:
    """The amount is the anchor: everything after it on the same flattened
    line is "vendor [+ optional non-competitive rationale]". Returns None
    when neither currency-symbol layout matches (spec Part 8 known case:
    Ottawa report tables place '$' before or after the amount by period)."""
    amount_match = AMOUNT_VENDOR_PREFIX.search(flattened) or AMOUNT_VENDOR_SUFFIX.search(flattened)
    if not amount_match:
        return None
    amount = float(amount_match.group(1).replace(",", ""))
    vendor_and_rationale = amount_match.group(2).strip()
    rationale_match = re.search(r"\s+(Section\s+\d+.*)$", vendor_and_rationale, re.IGNORECASE)
    if rationale_match:
        vendor = vendor_and_rationale[:rationale_match.start()].strip()
        rationale = rationale_match.group(1).strip()
    else:
        vendor, rationale = vendor_and_rationale, None
    return amount_match, amount, vendor, rationale


def extract_records(path: Path, source_id: str = "ottawa_contracts_awarded") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    reader = PdfReader(str(path), strict=False)
    pages = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n".join(pages)
    period_start, period_end = report_period(full_text, path)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    raw_ref = str(path)
    starts = [index for index, line in enumerate(lines) if RECORD_START.match(line)]
    records: list[dict[str, Any]] = []
    for position, start_index in enumerate(starts):
        end_index = starts[position + 1] if position + 1 < len(starts) else len(lines)
        match = RECORD_START.match(lines[start_index])
        assert match is not None
        item_number, contract_id = match.groups()
        block = lines[start_index:end_index]
        flattened = clean_text(block)
        parsed = _parse_amount_vendor_rationale(flattened)
        if parsed is None:
            continue
        amount_match, amount, vendor, rationale = parsed

        department = next((department for department in DEPARTMENTS if department in flattened), "Unknown Ottawa department")
        approval_match = re.search(r"\b(Initial|Extension|Amendment)\b", flattened, re.IGNORECASE)
        approval_type = approval_match.group(1).title() if approval_match else None

        # The description is whatever text sits between the department name
        # and the approval type (falling back to the amount's position if no
        # approval type was found) -- neither boundary is a dedicated field
        # in the source text, both are inferred from where the other parsed
        # values happen to land in the flattened line.
        description_start = flattened.find(department) + len(department) if department in flattened else len(contract_id)
        description_end = approval_match.start() if approval_match else amount_match.start()
        description = flattened[description_start:description_end].strip(" -")

        # 0.95 when every contextual field the parser hunts for was found;
        # 0.85 when any was missing (a sign the row layout deviated from the
        # expected table shape). Parser self-assessment, not measured
        # accuracy -- see this source's coverage known_gaps.
        confidence = 0.95 if period_end and department != "Unknown Ottawa department" and approval_type and rationale else 0.85
        release_id = f"{source_id}:{contract_id}:{item_number}"
        records.append({
            "ocid": f"{source_id}:{contract_id}",
            "id": release_id,
            "date": period_end,
            "initiationType": "tender",
            "tag": ["award", "contract"],
            "buyer": {"name": department, "id": f"ottawa:department:{hashlib.sha1(department.encode()).hexdigest()[:12]}", "jurisdiction": "ottawa"},
            "awards": [{
                "id": contract_id,
                "date": period_end,
                "value": {"amount": amount, "currency": "CAD"},
                "suppliers": [{"name": vendor, "id": None}],
                "description": description or None,
                "items": [{"classification": {"scheme": "UNSPSC", "id": "UNKNOWN"}}],
            }],
            "contracts": [{"period": {"startDate": period_start, "endDate": period_end}, "awardID": contract_id}],
            "_provenance": {
                "source_id": source_id,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "mapping_version": "phase-4-manual",
                "raw_ref": raw_ref,
                "field_origins": {"ocid": "Contract", "id": "Item#", "buyer.name": "Department", "awards[].value.amount": "Amount", "awards[].suppliers[].name": "Vendor", "awards[].description": "Description"},
                "extraction_conf": confidence,
                "report_period_start": period_start,
                "report_period_end": period_end,
                "approval_request_type": approval_type,
                "non_competitive_rationale": rationale,
            },
        })
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    instrumentation = {"source_id": source_id, "document": raw_ref, "pages": len(pages), "records_extracted": len(records), "latency_ms": elapsed_ms, "model_tokens": 0, "model_cost_usd": 0.0, "parser": "pypdf-deterministic", "validation_outcome": "pending"}
    return records, instrumentation


def extract_directory(input_dir: Path, output_path: Path, log_path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.pdf")):
        records, event = extract_records(path)
        all_records.extend(records)
        events.append(event)
    deduplicated: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for record in all_records:
        key = record["ocid"]
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = record
            continue
        duplicate_count += 1
        existing_refs = existing["_provenance"].setdefault("raw_refs", [existing["_provenance"]["raw_ref"]])
        if record["_provenance"]["raw_ref"] not in existing_refs:
            existing_refs.append(record["_provenance"]["raw_ref"])
        existing_description = existing["awards"][0].get("description") or ""
        record_description = record["awards"][0].get("description") or ""
        if (record["_provenance"]["extraction_conf"], len(record_description)) > (existing["_provenance"]["extraction_conf"], len(existing_description)):
            record["_provenance"]["raw_refs"] = existing_refs
            deduplicated[key] = record
    all_records = list(deduplicated.values())[:limit]
    validate_releases(all_records)
    for event in events:
        event["validation_outcome"] = "passed"
        event["duplicate_contracts_removed"] = duplicate_count
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as stream:
        for record in all_records:
            stream.write(json.dumps(record) + "\n")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")
    return all_records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    records = extract_directory(args.input_dir, args.output, args.log)
    print(f"extracted and validated {len(records)} Ottawa records")


if __name__ == "__main__":
    main()