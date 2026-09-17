"""Executable transform registry for mapping.yaml.

Each transform is a real function: it receives the raw string values
extracted from the mapping entry's source field(s), in declared order, plus
the entry itself (for `constant:` values), and returns the canonical value.
`apply_mapping.py` executes these when applying a mapping; the validation
gate in `generate_mapping.py` rejects any transform name not registered
here (spec Part 7, rule 3: unknown transforms fail validation).

Fallback chains live in the mapping config (`source_fields: [primary,
fallback]`), not in transform names -- a transform sees the values and
picks; the config declares which columns are candidates.
"""

from collections.abc import Callable
from typing import Any

from .validate import parse_date


def _first_nonempty(values: list[str]) -> str:
    return next((value for value in values if value), "")


def _to_float(value: str) -> float:
    return float(value.replace(",", "").replace("$", "") or "0")


def _direct(values: list[str], entry: dict[str, Any]) -> str:
    """First non-empty source value, verbatim."""
    return _first_nonempty(values)


def _parse_date(values: list[str], entry: dict[str, Any]) -> str | None:
    return parse_date(_first_nonempty(values) or None)


def _parse_currency(values: list[str], entry: dict[str, Any]) -> float:
    return _to_float(_first_nonempty(values))


def _parse_currency_with_total_fallback(values: list[str], entry: dict[str, Any]) -> float:
    """Amendment rows publish a (possibly negative) delta in the primary
    column with the running contract total beside it; a negative primary
    value falls back to the second declared column."""
    amount = _to_float(values[0] if values else "")
    if amount < 0 and len(values) > 1:
        amount = _to_float(values[1])
    return amount


def _default_cad(values: list[str], entry: dict[str, Any]) -> str:
    return _first_nonempty(values) or "CAD"


def _constant(values: list[str], entry: dict[str, Any]) -> Any:
    """Value comes from the entry's `constant:` key, not the row."""
    return entry["constant"]


def _unmapped(values: list[str], entry: dict[str, Any]) -> None:
    return None


Transform = Callable[[list[str], dict[str, Any]], Any]

TRANSFORMS: dict[str, Transform] = {
    "direct": _direct,
    "first_present": _direct,
    "parse_date": _parse_date,
    "parse_currency": _parse_currency,
    "parse_nonnegative_currency_with_total_fallback": _parse_currency_with_total_fallback,
    "default_cad": _default_cad,
    "constant": _constant,
    "unmapped": _unmapped,
    "none": _unmapped,
}


def is_registered(name: str | None) -> bool:
    return name in TRANSFORMS
