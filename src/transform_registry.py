"""Fixed transform registry used by generated mapping validation."""

from collections.abc import Callable
from typing import Any


def _identity(value: Any) -> Any:
    return value


def _parse_currency(value: Any) -> float:
    return float(str(value or "0").replace(",", "").replace("$", ""))


def _parse_date(value: Any) -> Any:
    from .validate import parse_date

    return parse_date(str(value)) if value else None


TRANSFORMS: dict[str, Callable[..., Any]] = {
    "direct": _identity,
    "direct_or_reference": _identity,
    "direct_or_operating_name": _identity,
    "direct_or_title": _identity,
    "first_present": _identity,
    "default_cad": _identity,
    "parse_currency": _parse_currency,
    "parse_nonnegative_currency_with_amount_fallback": _parse_currency,
    "parse_date": _parse_date,
    "parse_date_or_publication_date": _parse_date,
    "parse_date_mmddyyyy": _parse_date,
    "parse_date_mmddyyyy_or_posting_date": _parse_date,
    "none": _identity,
    "unmapped": _identity,
}


def is_registered(name: str | None) -> bool:
    return name in TRANSFORMS