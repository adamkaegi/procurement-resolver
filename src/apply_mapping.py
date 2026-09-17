"""Apply a source's reviewed mapping.yaml to its raw CSV, deterministically.

The mapping config is executable, not documentation: each entry names the
canonical field, the source column(s) to read (fallback order declared in
`source_fields`), and a transform registered in `transform_registry.py`.
This module interprets that config generically -- there is no per-source
Python branch (see docs/DECISIONS.md, "mapping.yaml is executed, not
decorative").

Structural fields no source publishes are supplied here, uniformly:
`initiationType` ("tender"), `tag` (["award"]), `buyer.id`
("<source_id>:buyer"), `buyer.jurisdiction` (from config), the award
mirroring of release id/date, and the provenance block. A mapping entry for
one of those structural fields (disposition "unmapped") is documentation of
the source's gap, not something this interpreter reads.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .transform_registry import TRANSFORMS
from .validate import validate_releases

# Canonical fields the interpreter reads from the mapping to assemble a
# release. Everything else in the release shape is structural (see module
# docstring).
_MAPPED_FIELDS = (
    "ocid",
    "id",
    "date",
    "buyer.name",
    "awards[].suppliers[].name",
    "awards[].value.amount",
    "awards[].value.currency",
    "awards[].description",
    "awards[].items[].classification.id",
    "contracts[].period.startDate",
    "contracts[].period.endDate",
)


def _extract(entry: dict[str, Any] | None, row: dict[str, str]) -> Any:
    if entry is None:
        return None
    fields = entry.get("source_fields") or ([entry["source_field"]] if entry.get("source_field") else [])
    values = [(row.get(field) or "").strip() for field in fields]
    transform = TRANSFORMS[entry.get("transform", "unmapped")]
    return transform(values, entry)


def _release(row: dict[str, str], config: dict[str, Any], raw_ref: str) -> dict[str, Any]:
    entries = {entry["canonical"]: entry for entry in config["mappings"]}
    missing = [field for field in ("ocid", "id") if field not in entries]
    if missing:
        raise ValueError(
            f"mapping for {config['source_id']!r} lacks required canonical field(s) {missing} -- "
            "every source must map a release identity"
        )

    def value_of(canonical: str, default: Any = None) -> Any:
        extracted = _extract(entries.get(canonical), row)
        return extracted if extracted not in ("", None) else default

    source_id = config["source_id"]
    ocid = value_of("ocid")
    release_id = value_of("id")
    date = value_of("date")
    classification = value_of("awards[].items[].classification.id", "")
    # A source may declare its classification scheme (e.g. ontario_vor's
    # "VOR"); federal columns carry either short GSIN-style codes or long
    # UNSPSC codes in the same field, where length is the only available
    # discriminator.
    scheme = config.get("classification_scheme") or ("GSIN" if len(classification) <= 6 else "UNSPSC")
    start = value_of("contracts[].period.startDate")
    end = value_of("contracts[].period.endDate")

    return {
        "ocid": ocid,
        "id": release_id,
        "date": date,
        "initiationType": "tender",
        "tag": ["award"],
        "buyer": {
            "name": value_of("buyer.name", "Unknown"),
            "id": f"{source_id}:buyer",
            "jurisdiction": config["jurisdiction"],
        },
        "awards": [{
            "id": release_id,
            "date": date,
            "value": {
                "amount": value_of("awards[].value.amount", 0.0),
                "currency": value_of("awards[].value.currency", "CAD"),
            },
            "suppliers": [{"name": value_of("awards[].suppliers[].name", "Unknown"), "id": None}],
            "description": value_of("awards[].description"),
            "items": [{"classification": {"scheme": scheme, "id": classification or "UNKNOWN"}}],
            "contractPeriod": {"startDate": start, "endDate": end},
        }],
        "contracts": [{"period": {"startDate": start, "endDate": end}, "awardID": release_id}],
        "_provenance": {
            "source_id": source_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "mapping_version": config["mapping_version"],
            "raw_ref": raw_ref,
            "field_origins": {
                entry["canonical"]: entry.get("source_field", entry.get("source_fields"))
                for entry in config["mappings"]
            },
            "extraction_conf": None,
        },
    }


def _is_usable_row(row: dict[str, str], config: dict[str, Any]) -> bool:
    """False for blank rows and, when the source config names one
    (e.g. ontario_vor's VOR number), rows missing their required field --
    footer/note rows that aren't vendors (see docs/FAILURES.md #12)."""
    has_any_value = any(value.strip() for value in row.values() if value)
    required_field = config.get("required_source_field")
    return bool(has_any_value and (not required_field or (row.get(required_field) or "").strip()))


def ingest_csv(path: Path, config_path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    config = yaml.safe_load(config_path.read_text())
    with path.open(newline="", encoding=config.get("encoding", "utf-8-sig")) as stream:
        for _ in range(config.get("skip_rows", 0)):
            next(stream, None)
        reader = csv.DictReader(stream)
        reader.fieldnames = [field.strip() for field in (reader.fieldnames or [])]
        rows = [
            {key.strip(): value for key, value in row.items() if key is not None}
            for row in reader
            if _is_usable_row(row, config)
        ]
        releases = [_release(row, config, str(path)) for row in rows[:limit]]
    validate_releases(releases)
    return releases
