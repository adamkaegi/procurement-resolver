"""Tests for src/validate.py: schema validation and date parsing."""

import pytest

from src.validate import parse_date, validate_release, validate_releases

MINIMAL_RELEASE = {
    "ocid": "abc-1",
    "id": "abc-1",
    "date": "2024-01-01T00:00:00+00:00",
    "initiationType": "tender",
    "tag": ["award"],
    "buyer": {"name": "Test Buyer", "id": "buyer:1", "jurisdiction": "federal"},
    "awards": [
        {
            "id": "award-1",
            "date": "2024-01-01T00:00:00+00:00",
            "value": {"amount": 100.0, "currency": "CAD"},
            "suppliers": [{"name": "Test Vendor", "id": None}],
        }
    ],
}


def test_minimal_release_validates():
    assert validate_release(MINIMAL_RELEASE) == []


def test_missing_required_field_fails():
    release = {k: v for k, v in MINIMAL_RELEASE.items() if k != "buyer"}
    errors = validate_release(release)
    assert errors, "dropping a required field should produce validation errors"


def test_negative_amount_fails():
    release = dict(MINIMAL_RELEASE)
    release["awards"] = [{**MINIMAL_RELEASE["awards"][0], "value": {"amount": -5.0, "currency": "CAD"}}]
    errors = validate_release(release)
    assert errors


def test_bad_currency_code_fails():
    release = dict(MINIMAL_RELEASE)
    release["awards"] = [{**MINIMAL_RELEASE["awards"][0], "value": {"amount": 5.0, "currency": "dollars"}}]
    errors = validate_release(release)
    assert errors


def test_initiation_type_must_be_tender():
    release = {**MINIMAL_RELEASE, "initiationType": "planning"}
    assert validate_release(release)


def test_validate_releases_counts_and_raises_with_message():
    assert validate_releases([MINIMAL_RELEASE, MINIMAL_RELEASE]) == 2
    bad = {k: v for k, v in MINIMAL_RELEASE.items() if k != "awards"}
    with pytest.raises(ValueError, match="release 2 failed validation"):
        validate_releases([MINIMAL_RELEASE, bad])


@pytest.mark.parametrize(
    "value,expected_prefix",
    [
        ("2024-01-15", "2024-01-15"),
        ("2024-01-15T00:00:00Z", "2024-01-15"),
        ("01/15/2024", "2024-01-15"),
    ],
)
def test_parse_date_accepts_known_formats(value, expected_prefix):
    result = parse_date(value)
    assert result is not None
    assert result.startswith(expected_prefix)


@pytest.mark.parametrize("value", [None, "", "TBD", "N/A", "unknown"])
def test_parse_date_treats_placeholders_as_none(value):
    assert parse_date(value) is None


def test_parse_date_rejects_garbage():
    with pytest.raises(ValueError):
        parse_date("not a date")
