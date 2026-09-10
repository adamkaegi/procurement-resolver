"""Validation helpers for canonical procurement releases."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def load_validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "schema/ocds_subset.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_release(release: dict[str, Any]) -> list[str]:
    return [error.message for error in load_validator().iter_errors(release)]


def validate_releases(releases: Iterable[dict[str, Any]]) -> int:
    count = 0
    for count, release in enumerate(releases, 1):
        errors = validate_release(release)
        if errors:
            raise ValueError(f"release {count} failed validation: {'; '.join(errors)}")
    return count


def parse_date(value: str | None) -> str | None:
    if not value or value.strip().upper() in {"TBD", "N/A", "NA", "UNKNOWN"}:
        return None
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).isoformat()
        except ValueError:
            continue
    return datetime.strptime(value, "%m/%d/%Y").replace(tzinfo=timezone.utc).isoformat()