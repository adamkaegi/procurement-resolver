"""Tests for src/ingest_ottawa_open_data.py: deterministic Excel extraction
of the 2020-2022 Ottawa historical contracts-awarded workbooks.

Format A (2020) and Format B (2021, 2022) are built as small synthetic
workbooks here so a header-lookup or period-parsing regression is caught
without touching the real archived files under data/raw/.
"""

from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from src.ingest_ottawa_open_data import extract_all, extract_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw/ottawa_historical_contracts"


def _write_format_a_workbook(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "FEDCO Q1-Q2"
    sheet.append(["Item #", "Line Item(departments)", "PO", "PO Creation Date", "Department ",
                  "Service Code", "Branch Code", "Description ", "Professional/ Consulting Services",
                  "Follow-on/ Amendment", "Amount", "Vendor Name", "City", "Region", "Vendor ",
                  "Non Competitive Rationale "])
    sheet.append([1, 1, 45090062, datetime(2020, 5, 19), "City Managers Office", "NA", "NA",
                  "Professional services.", "PE", None, 101760, "ERNST & YOUNG LLP", "TORONTO", "ON",
                  "ERNST & YOUNG LLP\nTORONTO ON", "Section 22(1)(f) - Special Circumstance"])
    # A row with no PO Creation Date (observed real case: a "P-Card" rollup row)
    # must be excluded, not loaded with a fabricated date.
    sheet.append([2, 2, "P-Card", None, "Recreation, Cultural & Facility Services", "NA", "NA",
                  "Preventative maintenance.", None, "E", 105783.84, "EXER-TECH INC.", "OTTAWA", "ON",
                  "EXER-TECH INC.\nOTTAWA ON", None])
    workbook.save(path)


def _write_format_b_workbook(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Table 1"
    sheet.append(["Transit", None, None,
                  "CONTRACTS>$25,000 AWARDED UNDER DELEGATION OF AUTHORITY FOR THE PERIOD OF JANUARY 1, 2021 TO JUNE 30, 2021",
                  None, None, None, None, None, "Document 1"])
    sheet.append(["Item #", "Contract", "Department", "Service", "Description",
                  "Professional/Consulting Services", "Contract Approval Request Type", "Amount",
                  "Vendor", "Non-Competitive Rationale"])
    sheet.append([1, "00119-55734-G01", "Transit Services", "Transit Operations Service",
                  "Supply and deliver Kleenoil Products for Transit Operations", None,
                  "Extension ( As per Section 32(2))", 153345, "KLEENOIL FILTRATION CANADA LTD",
                  "Section 22 (1) (D) - Absence of competition"])
    workbook.save(path)


def test_format_a_maps_core_fields_and_skips_rows_without_a_date(tmp_path):
    path = tmp_path / "2020_Contracts_Awarded_greater_than_25000.xlsx"
    _write_format_a_workbook(path)
    records, event = extract_workbook(path)

    assert len(records) == 1
    release = records[0]
    assert release["ocid"] == "ottawa_historical_contracts:45090062"
    assert release["date"] == "2020-05-19T00:00:00+00:00"
    assert release["buyer"]["name"] == "City Managers Office"
    assert release["buyer"]["jurisdiction"] == "ottawa"
    assert release["awards"][0]["suppliers"][0]["name"] == "ERNST & YOUNG LLP"
    assert release["awards"][0]["value"]["amount"] == 101760.0
    assert release["_provenance"]["extraction_conf"] == 0.98
    assert event["records_extracted"] == 1


def test_format_b_parses_period_from_title_row_and_maps_core_fields(tmp_path):
    path = tmp_path / "2021_Contracts_Awarded_greater_than_25000.xlsx"
    _write_format_b_workbook(path)
    records, event = extract_workbook(path)

    assert len(records) == 1
    release = records[0]
    assert release["ocid"] == "ottawa_historical_contracts:00119-55734-G01"
    # no per-row date is published in this format; date falls back to period end.
    assert release["date"] == "2021-06-30T23:59:59+00:00"
    assert release["contracts"][0]["period"]["startDate"] == "2021-01-01T00:00:00+00:00"
    assert release["buyer"]["name"] == "Transit Services"
    assert release["awards"][0]["suppliers"][0]["name"] == "KLEENOIL FILTRATION CANADA LTD"
    assert release["awards"][0]["value"]["amount"] == 153345.0
    assert release["_provenance"]["approval_request_type"] == "Extension ( As per Section 32(2))"
    assert event["records_extracted"] == 1


@pytest.mark.skipif(not RAW_DIR.exists(), reason="data/raw/ottawa_historical_contracts not present locally")
def test_extract_all_deduplicates_and_validates_against_real_archives(tmp_path):
    output_path = tmp_path / "ottawa_historical.jsonl"
    log_path = tmp_path / "ottawa_historical.log.jsonl"
    records = extract_all(RAW_DIR, output_path, log_path)

    assert len(records) > 0
    ocids = [r["ocid"] for r in records]
    assert len(ocids) == len(set(ocids))
    assert all(r["_provenance"]["extraction_conf"] == 0.98 for r in records)
    # source.yaml's zero-overlap decision: nothing here should reach 2023,
    # where ottawa_contracts_awarded's PDF coverage begins.
    assert all((r["date"] or "0") < "2023-01-01" for r in records)
    assert output_path.exists()
    assert log_path.exists()
