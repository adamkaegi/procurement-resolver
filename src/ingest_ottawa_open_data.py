"""Extract City of Ottawa delegated-authority contracts from structured Excel
workbooks (2020-2022), published on open.ottawa.ca before the City switched
to bi-annual ArcGIS Feature Services (which ottawa_contracts_awarded's PDF
reports otherwise stand in for from 2023 onward).

These are spreadsheet cells, not OCR/regex-parsed PDF text, so extraction
confidence is fixed higher than extract_documents.py's PDF path -- see
EXTRACTION_CONFIDENCE below and the ADR in docs/DECISIONS.md.

Two internal layouts, by year (see sources/ottawa_historical_contracts/source.yaml
for why 2016-2019 was excluded and why this stops at 2022):

  Format A (2020 only): one header row, one row per contract.
  Format B (2021, 2022): a merged title row (carrying the report period as
  free text, parsed the same way extract_documents.report_period does for
  the PDF reports) followed by a header row, one row per contract.

Column position varies release to release (a "Service" column appears on
Transit sheets and not others); both formats resolve columns by normalized
header name rather than position, which is what actually keeps this
tolerant of the header text drifting ("Dept" vs "Dept." vs "Department").
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl

from .extract_documents import PERIOD
from .validate import validate_releases

SOURCE_ID = "ottawa_historical_contracts"
EXTRACTION_CONFIDENCE = 0.98


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _header_index(header: tuple[Any, ...], *candidates: str) -> int | None:
    normalized = [_normalize_header(cell) for cell in header]
    for candidate in candidates:
        target = _normalize_header(candidate)
        if target in normalized:
            return normalized.index(target)
    return None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    return text or None


def _department_buyer(name: str | None) -> dict[str, Any]:
    name = name or "Unknown Ottawa department"
    return {"name": name, "id": f"ottawa:department:{hashlib.sha1(name.encode()).hexdigest()[:12]}", "jurisdiction": "ottawa"}


def _release(
    contract_id: str, item_number: Any, date_iso: str | None, period_start: str | None, period_end: str | None,
    department: str | None, description: str | None, amount: float, vendor: str,
    rationale: str | None, approval_type: str | None, raw_ref: str, field_origins: dict[str, str],
) -> dict[str, Any]:
    release_id = f"{SOURCE_ID}:{contract_id}:{item_number}"
    return {
        "ocid": f"{SOURCE_ID}:{contract_id}",
        "id": release_id,
        "date": date_iso,
        "initiationType": "tender",
        "tag": ["award", "contract"],
        "buyer": _department_buyer(department),
        "awards": [{
            "id": contract_id,
            "date": date_iso,
            "value": {"amount": amount, "currency": "CAD"},
            "suppliers": [{"name": vendor, "id": None}],
            "description": description,
            "items": [{"classification": {"scheme": "UNSPSC", "id": "UNKNOWN"}}],
        }],
        "contracts": [{"period": {"startDate": period_start, "endDate": period_end}, "awardID": contract_id}],
        "_provenance": {
            "source_id": SOURCE_ID,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "mapping_version": "phase-6-manual",
            "raw_ref": raw_ref,
            "field_origins": field_origins,
            "extraction_conf": EXTRACTION_CONFIDENCE,
            "report_period_start": period_start,
            "report_period_end": period_end,
            "approval_request_type": approval_type,
            "non_competitive_rationale": rationale,
        },
    }


def _extract_format_a(header: tuple[Any, ...], rows: list[tuple[Any, ...]], raw_ref: str) -> list[dict[str, Any]]:
    """2020: one flat header row, one row per contract, a real per-row date."""
    item_idx = _header_index(header, "item #")
    po_idx = _header_index(header, "po")
    date_idx = _header_index(header, "po creation date")
    dept_idx = _header_index(header, "department", "service")
    desc_idx = _header_index(header, "description")
    amount_idx = _header_index(header, "amount")
    vendor_idx = _header_index(header, "vendor name", "vendor")
    rationale_idx = _header_index(header, "non competitive rationale")
    amendment_idx = _header_index(header, "follow-on/ amendment", "follow-on/amendment")
    if po_idx is None or amount_idx is None or vendor_idx is None:
        return []
    field_origins = {
        "ocid": "PO", "id": "Item #", "buyer.name": "Department/Service",
        "awards[].value.amount": "Amount", "awards[].suppliers[].name": "Vendor Name",
        "awards[].description": "Description", "date": "PO Creation Date",
    }
    records = []
    for row in rows:
        if item_idx is None or item_idx >= len(row) or not isinstance(row[item_idx], int):
            continue
        po = row[po_idx] if po_idx < len(row) else None
        amount = row[amount_idx] if amount_idx < len(row) else None
        vendor = _clean(row[vendor_idx]) if vendor_idx < len(row) else None
        if po is None or vendor is None or not isinstance(amount, (int, float)):
            continue
        creation_date = row[date_idx] if date_idx is not None and date_idx < len(row) else None
        if not isinstance(creation_date, datetime):
            # A handful of rows (observed: PO "P-Card", a rolled-up
            # procurement-card summary line, not an individual delegated-
            # authority contract) carry no PO Creation Date at all. date is
            # a required, non-nullable schema field; abstaining by skipping
            # the row is preferred to fabricating one.
            continue
        date_iso = creation_date.replace(tzinfo=timezone.utc).isoformat()
        rationale = _clean(row[rationale_idx]) if rationale_idx is not None and rationale_idx < len(row) else None
        approval_type = _clean(row[amendment_idx]) if amendment_idx is not None and amendment_idx < len(row) else None
        records.append(_release(
            contract_id=str(po),
            item_number=row[item_idx],
            date_iso=date_iso,
            period_start=date_iso,
            period_end=None,
            department=_clean(row[dept_idx]) if dept_idx is not None and dept_idx < len(row) else None,
            description=_clean(row[desc_idx]) if desc_idx is not None and desc_idx < len(row) else None,
            amount=float(amount),
            vendor=vendor,
            rationale=rationale,
            approval_type=approval_type,
            raw_ref=raw_ref,
            field_origins=field_origins,
        ))
    return records


def _extract_format_b(title_row: tuple[Any, ...], header: tuple[Any, ...], rows: list[tuple[Any, ...]], raw_ref: str) -> list[dict[str, Any]]:
    """2021, 2022: a merged title row carrying the report period, then a
    header row whose column set varies (Transit sheets add a 'Service'
    column), then one row per contract with no per-row date at all."""
    title_text = " ".join(_clean(cell) or "" for cell in title_row)
    match = PERIOD.search(title_text)
    period_start = period_end = None
    if match:
        start_month, start_day, start_year, end_month, end_day, end_year = match.groups()
        start = datetime.strptime(f"{start_month} {start_day} {start_year}", "%B %d %Y").replace(tzinfo=timezone.utc)
        end = datetime.strptime(f"{end_month} {end_day} {end_year}", "%B %d %Y").replace(tzinfo=timezone.utc)
        period_start, period_end = start.isoformat(), end.replace(hour=23, minute=59, second=59).isoformat()

    item_idx = _header_index(header, "item #")
    contract_idx = _header_index(header, "contract")
    dept_idx = _header_index(header, "department")
    desc_idx = _header_index(header, "description")
    amount_idx = _header_index(header, "amount")
    vendor_idx = _header_index(header, "vendor")
    rationale_idx = _header_index(header, "non-competitive rationale")
    approval_idx = _header_index(header, "contract approval request type")
    if contract_idx is None or amount_idx is None or vendor_idx is None:
        return []
    field_origins = {
        "ocid": "Contract", "id": "Item #", "buyer.name": "Department",
        "awards[].value.amount": "Amount", "awards[].suppliers[].name": "Vendor",
        "awards[].description": "Description", "date": "report period end (no per-row date published)",
    }
    records = []
    for row in rows:
        if item_idx is None or item_idx >= len(row) or not isinstance(row[item_idx], int):
            continue
        contract = _clean(row[contract_idx]) if contract_idx < len(row) else None
        amount = row[amount_idx] if amount_idx < len(row) else None
        vendor = _clean(row[vendor_idx]) if vendor_idx < len(row) else None
        if contract is None or vendor is None or not isinstance(amount, (int, float)):
            continue
        records.append(_release(
            contract_id=contract,
            item_number=row[item_idx],
            date_iso=period_end,
            period_start=period_start,
            period_end=period_end,
            department=_clean(row[dept_idx]) if dept_idx is not None and dept_idx < len(row) else None,
            description=_clean(row[desc_idx]) if desc_idx is not None and desc_idx < len(row) else None,
            amount=float(amount),
            vendor=vendor,
            rationale=_clean(row[rationale_idx]) if rationale_idx is not None and rationale_idx < len(row) else None,
            approval_type=_clean(row[approval_idx]) if approval_idx is not None and approval_idx < len(row) else None,
            raw_ref=raw_ref,
            field_origins=field_origins,
        ))
    return records


def extract_workbook(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    raw_ref = str(path)
    records: list[dict[str, Any]] = []
    for worksheet in workbook.worksheets:
        rows_iter = worksheet.iter_rows(values_only=True)
        first_row = next(rows_iter, None)
        if first_row is None:
            continue
        if _normalize_header(first_row[0]) == "item #":
            records.extend(_extract_format_a(first_row, list(rows_iter), raw_ref))
        else:
            header_row = next(rows_iter, None)
            if header_row is None:
                continue
            records.extend(_extract_format_b(first_row, header_row, list(rows_iter), raw_ref))
    workbook.close()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    instrumentation = {
        "source_id": SOURCE_ID, "document": raw_ref, "sheets": len(workbook.sheetnames),
        "records_extracted": len(records), "latency_ms": elapsed_ms, "model_tokens": 0,
        "model_cost_usd": 0.0, "parser": "openpyxl-deterministic", "validation_outcome": "pending",
    }
    return records, instrumentation


def extract_all(input_dir: Path, output_path: Path, log_path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    # rglob, not glob: unlike ottawa_contracts_awarded's flat PDF directory,
    # these were archived through fetch.py's timestamped-subdirectory
    # convention (data/raw/<source_id>/<timestamp>/<file>).
    for path in sorted(input_dir.rglob("*.xlsx")):
        records, event = extract_workbook(path)
        all_records.extend(records)
        events.append(event)

    # Same dedup contract as extract_documents.extract_directory: keep the
    # richer record if the same ocid is somehow seen twice (e.g. a contract
    # spanning two half-year sheets), tracking every raw file it came from.
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
        if len(record_description) > len(existing_description):
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
