"""Tests for src/extract_documents.py: deterministic Ottawa PDF extraction."""

from pathlib import Path

import pytest

from src.extract_documents import clean_text, extract_directory, report_period

ROOT = Path(__file__).resolve().parents[1]
RAW_OTTAWA_DIR = ROOT / "data/raw/ottawa_contracts_awarded"


def test_clean_text_collapses_whitespace_and_normalizes_hyphen():
    lines = ["  Line one  ", "Line‐two  ", "", "Line three"]
    assert clean_text(lines) == "Line one Line-two Line three"


@pytest.mark.parametrize(
    "text,expected_start_prefix,expected_end_prefix",
    [
        ("for the period of January 1, 2024 to June 30, 2024", "2024-01-01", "2024-06-30"),
        ("period July 1, 2023 to December 31, 2023", "2023-07-01", "2023-12-31"),
    ],
)
def test_report_period_parses_month_day_year_ranges(text, expected_start_prefix, expected_end_prefix):
    start, end = report_period(text, Path("irrelevant.pdf"))
    assert start.startswith(expected_start_prefix)
    assert end.startswith(expected_end_prefix)


def test_report_period_falls_back_on_known_mislabelled_filename():
    # docs/PROGRESS.md: this filename is off by one year; the report text supplies 2023.
    start, end = report_period("no matching period text here", Path("Jan-June 2024-AODA.pdf"))
    assert start == "2024-01-01T00:00:00+00:00"
    assert end == "2024-06-30T23:59:59+00:00"


def test_report_period_returns_none_when_nothing_matches():
    assert report_period("nothing relevant", Path("unrelated.pdf")) == (None, None)


@pytest.mark.skipif(not RAW_OTTAWA_DIR.exists(), reason="data/raw/ottawa_contracts_awarded not present locally")
def test_extract_directory_deduplicates_overlapping_reports_and_validates(tmp_path):
    output_path = tmp_path / "ottawa.jsonl"
    log_path = tmp_path / "ottawa.log.jsonl"
    records = extract_directory(RAW_OTTAWA_DIR, output_path, log_path)

    assert len(records) > 0
    # ocid (contract id) must be unique post-dedup: the whole point of the dedup pass.
    ocids = [r["ocid"] for r in records]
    assert len(ocids) == len(set(ocids))
    # every record from a PDF-extraction source must carry a numeric extraction confidence.
    assert all(isinstance(r["_provenance"]["extraction_conf"], float) for r in records)
    assert output_path.exists()
    assert log_path.exists()
