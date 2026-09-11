"""Tests for src/transform_registry.py: the fixed transform registry used by
the mapping generator's validation gate (spec Part 7, rule 3: unknown
transforms fail validation)."""

import pytest

from src.transform_registry import TRANSFORMS, is_registered


def test_is_registered_true_for_known_transform():
    assert is_registered("parse_currency") is True


def test_is_registered_false_for_unknown_transform():
    assert is_registered("does_not_exist") is False


def test_is_registered_false_for_none():
    assert is_registered(None) is False


@pytest.mark.parametrize(
    "raw,expected",
    [("1,234.50", 1234.50), ("$999", 999.0), ("", 0.0), (None, 0.0)],
)
def test_parse_currency_strips_formatting(raw, expected):
    assert TRANSFORMS["parse_currency"](raw) == expected


def test_parse_date_transform_delegates_to_validate_parse_date():
    assert TRANSFORMS["parse_date"]("2024-01-01").startswith("2024-01-01")
    assert TRANSFORMS["parse_date"]("") is None
    assert TRANSFORMS["parse_date"](None) is None


def test_identity_transforms_pass_value_through_unchanged():
    for name in ("direct", "first_present", "none", "unmapped"):
        assert TRANSFORMS[name]("Bell Canada") == "Bell Canada"
