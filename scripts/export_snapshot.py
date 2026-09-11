"""Export a static, gzip-compressed snapshot of the warehouse for docs/register.html
(the Artifact data browser). Read-only against data/warehouse.duckdb; writes
JSON/base64 fragments to demo/ (gitignored -- derived data, regenerate on demand).

Usage:
    uv run python scripts/export_snapshot.py
    # then paste demo/releases.b64, demo/entities.b64, demo/coverage.json
    # into the __RELEASES_B64__ / __ENTITIES_B64__ / __COVERAGE_JSON__
    # placeholders in a copy of the register.html template and republish.
"""

import base64
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from src import agent_tools as tools  # noqa: E402

DATABASE = ROOT / "data/warehouse.duckdb"
OUT_DIR = ROOT / "demo"


def _gzip_b64(obj) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.b64encode(gzip.compress(raw, compresslevel=9)).decode()


def export_releases(connection: duckdb.DuckDBPyConnection) -> str:
    rows = connection.execute(
        "SELECT source_id, json_extract_string(record, '$.buyer.jurisdiction'), "
        "json_extract_string(record, '$.buyer.name'), "
        "json_extract_string(record, '$.awards[0].suppliers[0].name'), "
        "json_extract(record, '$.awards[0].value.amount')::DOUBLE, "
        "substr(json_extract_string(record, '$.date'), 1, 10), "
        "json_extract_string(record, '$.awards[0].description'), ocid "
        "FROM releases"
    ).fetchall()
    data = [
        {"s": s, "j": j, "b": b, "v": v, "a": a, "d": d, "t": (t or "")[:200], "o": o}
        for s, j, b, v, a, d, t, o in rows
    ]
    return _gzip_b64(data)


def export_entities(connection: duckdb.DuckDBPyConnection) -> str:
    jurisdiction_map = tools.source_jurisdiction_map(connection)
    rows = connection.execute("SELECT DISTINCT entity_id, source_id FROM entity_link").fetchall()
    by_entity: dict[str, set[str]] = defaultdict(set)
    for entity_id, source_id in rows:
        by_entity[entity_id].add(jurisdiction_map.get(source_id))
    cross_entities = [eid for eid, js in by_entity.items() if len(js) > 1]

    entities_out = []
    for entity_id in cross_entities:
        profile = tools.entity_profile(connection, entity_id)
        exposure = tools.cross_level_exposure(connection, entity_id)
        entities_out.append({
            "entity_id": entity_id,
            "canonical_name": profile.canonical_name,
            "name_variants": profile.name_variants,
            "jurisdictions": profile.jurisdictions_present,
            "contract_count": len(profile.contracts),
            "declined": exposure.declined,
            "decline_reason": exposure.decline_reason,
            "exposures": [e.model_dump() for e in exposure.exposures],
        })
    entities_out.sort(key=lambda e: e["contract_count"], reverse=True)
    return _gzip_b64(entities_out)


def export_coverage(connection: duckdb.DuckDBPyConnection) -> str:
    entries = [e.model_dump() for e in tools.coverage(connection).entries]
    return json.dumps(entries, separators=(",", ":"))


def main() -> None:
    if not DATABASE.exists():
        raise FileNotFoundError(f"{DATABASE} does not exist. Run scripts/rebuild.py first.")
    OUT_DIR.mkdir(exist_ok=True)
    with duckdb.connect(str(DATABASE), read_only=True) as connection:
        (OUT_DIR / "releases.b64").write_text(export_releases(connection))
        (OUT_DIR / "entities.b64").write_text(export_entities(connection))
        (OUT_DIR / "coverage.json").write_text(export_coverage(connection))
    print(f"wrote releases.b64, entities.b64, coverage.json to {OUT_DIR}")


if __name__ == "__main__":
    main()
