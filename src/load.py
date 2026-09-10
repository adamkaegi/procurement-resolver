"""Load validated canonical releases into DuckDB."""

import json
from pathlib import Path
from typing import Any, Iterable

import duckdb


def load_releases(database: Path, releases: Iterable[dict[str, Any]]) -> None:
    rows = [(release["_provenance"]["source_id"], release["ocid"], json.dumps(release)) for release in releases]
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS releases (source_id VARCHAR, ocid VARCHAR, record JSON)")
        connection.executemany("INSERT INTO releases VALUES (?, ?, ?)", rows)