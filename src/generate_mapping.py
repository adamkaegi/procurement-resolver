"""Validation gate for generated source mappings (spec Part 7).

A generated mapping passes only if: every canonical field appears exactly
once with a valid disposition and reasoning; every named source field
exists verbatim in the raw header; every transform is registered; and --
the real test -- applying the mapping to sample rows through the actual
interpreter (`apply_mapping._release`) produces records that pass OCDS
subset validation. The gate is shared by every generation path (today:
`ollama_mapping.py`); there is no offline proposal engine here.
"""

from typing import Any

from .apply_mapping import _release
from .transform_registry import is_registered
from .validate import validate_release

CANONICAL_FIELDS = [
    "ocid", "id", "date", "initiationType", "tag", "buyer.name", "buyer.id",
    "buyer.jurisdiction", "awards[].id", "awards[].date", "awards[].value.amount",
    "awards[].value.currency", "awards[].suppliers[].name", "awards[].suppliers[].id",
    "awards[].items[].classification.scheme", "awards[].items[].classification.id",
    "awards[].description", "contracts[].period.startDate", "contracts[].period.endDate",
]


def validate_mapping(mapping: dict[str, Any], fields: list[str]) -> list[str]:
    errors: list[str] = []
    if not mapping.get("source_id") or not isinstance(mapping.get("mappings"), list):
        errors.append("mapping requires source_id and mappings")
    seen: set[str] = set()
    for item in mapping.get("mappings", []):
        canonical = item.get("canonical")
        if canonical in seen:
            errors.append(f"duplicate canonical field: {canonical}")
        seen.add(canonical)
        if canonical not in CANONICAL_FIELDS:
            errors.append(f"unknown canonical field: {canonical}")
        if item.get("disposition") not in {"mapped", "derived", "unmapped"}:
            errors.append(f"invalid disposition for {canonical}")
        if not item.get("reasoning"):
            errors.append(f"missing reasoning for {canonical}")
        if not is_registered(item.get("transform")):
            errors.append(f"unknown transform for {canonical}: {item.get('transform')}")
        if item.get("transform") == "constant" and "constant" not in item:
            errors.append(f"constant transform for {canonical} requires a 'constant' value")
        # "derived" items carry source_fields (a list); "mapped" items carry
        # source_field (a single string); "unmapped" and "constant" items
        # carry neither, so this falls back to [None], which the None-check
        # below skips.
        source_fields = item.get("source_fields", [item.get("source_field")])
        for source_field in source_fields:
            if source_field is not None and source_field not in fields:
                errors.append(f"unknown source field for {canonical}: {source_field}")
    missing = set(CANONICAL_FIELDS) - seen
    errors.extend(f"missing canonical field: {field}" for field in sorted(missing))
    return errors


def validate_sample(mapping: dict[str, Any], sample: list[dict[str, str]]) -> list[str]:
    """Apply the mapping to sample rows through the real interpreter and
    validate each produced record against the OCDS subset. This is what
    catches mappings that are structurally well-formed but produce invalid
    data (an unmapped required field, a value that doesn't parse)."""
    errors: list[str] = []
    for index, row in enumerate(sample, 1):
        try:
            release = _release(row, mapping, raw_ref="sample")
        except (ValueError, KeyError) as error:
            errors.append(f"sample row {index}: mapping could not be applied: {error}")
            continue
        errors.extend(f"sample row {index}: {message}" for message in validate_release(release))
    return errors
