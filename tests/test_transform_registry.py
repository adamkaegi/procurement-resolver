"""Tests for src/transform_registry.py: the executable transforms that
apply_mapping.py runs and the generation gate whitelists (spec Part 7,
rule 3: unknown transforms fail validation)."""

import pytest

from src.transform_registry import TRANSFORMS, is_registered


def test_is_registered_true_for_known_transform():
    assert is_registered("parse_currency") is True


def test_is_registered_false_for_unknown_transform():
    assert is_registered("does_not_exist") is False


def test_is_registered_false_for_none():
    assert is_registered(None) is False


def test_direct_takes_first_nonempty_value():
    assert TRANSFORMS["direct"](["", "Bell Canada", "ignored"], {}) == "Bell Canada"
    assert TRANSFORMS["first_present"](["", ""], {}) == ""


@pytest.mark.parametrize(
    "values,expected",
    [(["1,234.50"], 1234.50), (["$999"], 999.0), ([""], 0.0), ([], 0.0)],
)
def test_parse_currency_strips_formatting(values, expected):
    assert TRANSFORMS["parse_currency"](values, {}) == expected


def test_parse_currency_with_total_fallback_uses_second_value_when_negative():
    # amendment rows: negative delta in the primary column, running total beside it
    assert TRANSFORMS["parse_nonnegative_currency_with_total_fallback"](["-1", "75,000"], {}) == 75000.0
    assert TRANSFORMS["parse_nonnegative_currency_with_total_fallback"](["500", "75,000"], {}) == 500.0


def test_parse_date_transform_parses_first_nonempty():
    assert TRANSFORMS["parse_date"](["", "2024-01-01"], {}).startswith("2024-01-01")
    assert TRANSFORMS["parse_date"]([""], {}) is None


def test_default_cad_falls_back_only_when_empty():
    assert TRANSFORMS["default_cad"](["USD"], {}) == "USD"
    assert TRANSFORMS["default_cad"]([""], {}) == "CAD"


def test_constant_reads_the_entry_not_the_row():
    assert TRANSFORMS["constant"](["row value ignored"], {"constant": 0.0}) == 0.0


def test_unmapped_returns_none():
    assert TRANSFORMS["unmapped"](["anything"], {}) is None
    assert TRANSFORMS["none"](["anything"], {}) is None
