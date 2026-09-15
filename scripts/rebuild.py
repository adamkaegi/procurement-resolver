"""Deterministic, reproducible rebuild of data/warehouse.duckdb.

Reads only archived raw payloads already under data/raw/ (no network calls),
applies the reviewed source mappings, validates against the OCDS subset,
loads every in-scope source, then builds the entity/entity_link/coverage
tables from what was loaded.

This is the one command referenced by docs/RUNBOOK.md and CLAUDE.md success
criterion 4 for reproducing the warehouse. It is not the Phase 6 MCP server
and does not call one.

Usage:
    uv run python scripts/rebuild.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
import yaml  # noqa: E402

from src.apply_mapping import ingest_csv  # noqa: E402
from src.extract_documents import extract_directory  # noqa: E402
from src.ingest_ottawa_open_data import extract_all as extract_ottawa_historical  # noqa: E402
from src.load import load_releases  # noqa: E402
from src.resolve import build_entity_store  # noqa: E402
from src.validate import validate_releases  # noqa: E402

DATABASE = ROOT / "data/warehouse.duckdb"

# Which archived raw file feeds each CSV-mapped source. These are not fetched
# here -- data/raw/ is immutable and never re-fetched; this just names the
# already-archived payload each source's mapping.yaml was written against.
CSV_SOURCES = {
    "federal_contracts": ROOT / "data/raw/federal_contracts/phase1/contracts.csv",
    "canadabuys_award_notices": ROOT / "data/raw/canadabuys_award_notices/phase1/awards.csv",
    "ontario_vor": ROOT / "data/raw/ontario_vor/active/enterprise_vor_program.csv",
    "canadabuys_contract_history": ROOT / "data/raw/canadabuys_contract_history/20260915T181857Z/contractHistory-2024-2025.csv",
}

OTTAWA_RAW_DIR = ROOT / "data/raw/ottawa_contracts_awarded"
OTTAWA_PROCESSED = ROOT / "data/processed/ottawa_contracts_awarded.jsonl"
OTTAWA_LOG = ROOT / "data/processed/ottawa_extraction.jsonl"

OTTAWA_HISTORICAL_RAW_DIR = ROOT / "data/raw/ottawa_historical_contracts"
OTTAWA_HISTORICAL_PROCESSED = ROOT / "data/processed/ottawa_historical_contracts.jsonl"
OTTAWA_HISTORICAL_LOG = ROOT / "data/processed/ottawa_historical_extraction.jsonl"


def _record_cap(source_id: str) -> int:
    config = yaml.safe_load((ROOT / f"sources/{source_id}/source.yaml").read_text())
    return int(config.get("record_cap", 5000))


def load_csv_sources() -> dict[str, int]:
    counts: dict[str, int] = {}
    for source_id, raw_path in CSV_SOURCES.items():
        if not raw_path.exists():
            raise FileNotFoundError(
                f"archived raw payload missing for {source_id}: {raw_path}. "
                "data/raw/ is immutable and not re-fetched by this script."
            )
        mapping_path = ROOT / f"sources/{source_id}/mapping.yaml"
        releases = ingest_csv(raw_path, mapping_path, limit=_record_cap(source_id))
        load_releases(DATABASE, releases)
        counts[source_id] = len(releases)
    return counts


def load_ottawa() -> int:
    """Re-run the deterministic (no-network, no-model) PDF extraction from raw,
    then load the resulting canonical records. Licence verified 2026-09-10;
    see sources/ottawa_contracts_awarded/source.yaml and docs/BLOCKED.md."""
    if not OTTAWA_RAW_DIR.exists() or not any(OTTAWA_RAW_DIR.glob("*.pdf")):
        print(f"  [skip] no Ottawa raw PDFs found under {OTTAWA_RAW_DIR}")
        return 0
    records = extract_directory(OTTAWA_RAW_DIR, OTTAWA_PROCESSED, OTTAWA_LOG, limit=_record_cap("ottawa_contracts_awarded"))
    load_releases(DATABASE, records)
    return len(records)


def load_ottawa_historical() -> int:
    """Deterministic (no-network, no-model) openpyxl extraction of the
    2020-2022 Excel workbooks -- a separate source_id from the PDF-based
    ottawa_contracts_awarded; see sources/ottawa_historical_contracts/source.yaml
    for why, and docs/DECISIONS.md for the scope-expansion ADR."""
    if not OTTAWA_HISTORICAL_RAW_DIR.exists() or not any(OTTAWA_HISTORICAL_RAW_DIR.rglob("*.xlsx")):
        print(f"  [skip] no Ottawa historical raw workbooks found under {OTTAWA_HISTORICAL_RAW_DIR}")
        return 0
    records = extract_ottawa_historical(
        OTTAWA_HISTORICAL_RAW_DIR, OTTAWA_HISTORICAL_PROCESSED, OTTAWA_HISTORICAL_LOG,
        limit=_record_cap("ottawa_historical_contracts"),
    )
    load_releases(DATABASE, records)
    return len(records)


def main() -> None:
    if DATABASE.exists():
        print(f"removing existing {DATABASE}")
        DATABASE.unlink()

    with duckdb.connect(str(DATABASE)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS releases (source_id VARCHAR, ocid VARCHAR, record JSON)")

    print("loading CSV-mapped sources (federal, canadabuys x2, ontario_vor)...")
    counts = load_csv_sources()
    for source_id, count in counts.items():
        print(f"  {source_id}: {count} records")

    print("extracting and loading Ottawa (deterministic PDF parse, no network, no model)...")
    ottawa_count = load_ottawa()
    print(f"  ottawa_contracts_awarded: {ottawa_count} records")

    print("extracting and loading Ottawa historical 2020-2022 (deterministic Excel parse, no network, no model)...")
    ottawa_historical_count = load_ottawa_historical()
    print(f"  ottawa_historical_contracts: {ottawa_historical_count} records")

    with duckdb.connect(str(DATABASE)) as connection:
        total = connection.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        # Sanity check: every release still validates once round-tripped through JSON.
        rows = connection.execute("SELECT record FROM releases").fetchall()
        validate_releases(json.loads(raw) for (raw,) in rows)
        print(f"validated {total} releases round-tripped from the warehouse")

    print("building entity, entity_link, and coverage tables...")
    build_entity_store(DATABASE, ROOT)

    with duckdb.connect(str(DATABASE)) as connection:
        tables = [row[0] for row in connection.execute("SELECT table_name FROM information_schema.tables").fetchall()]
        print(f"tables: {sorted(tables)}")
        by_source = connection.execute("SELECT source_id, COUNT(*) FROM releases GROUP BY 1 ORDER BY 1").fetchall()
        print(f"releases by source: {by_source}")
        entity_count = connection.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
        link_count = connection.execute("SELECT COUNT(*) FROM entity_link").fetchone()[0]
        coverage_rows = connection.execute("SELECT source_id, jurisdiction, value_threshold, record_count, known_gaps FROM coverage ORDER BY 1").fetchall()
        print(f"entity: {entity_count} rows, entity_link: {link_count} rows")
        print("coverage:")
        for row in coverage_rows:
            print(f"  {row}")

    print("rebuild complete.")


if __name__ == "__main__":
    main()
