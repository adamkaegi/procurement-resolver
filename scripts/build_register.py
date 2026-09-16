"""Build the self-contained register.html: data (via export_snapshot's
functions, reused not duplicated) + the Fraunces font asset, merged into
demo/register_template.html's placeholders.

This closes the gap export_snapshot.py's own docstring used to describe as
a manual step ("paste ... into the placeholders ... and republish"). One
command now produces one ready-to-serve file:

    uv run python scripts/build_register.py

Reads data/warehouse.duckdb (read-only) and demo/assets/Fraunces-Variable.ttf
(committed, no network call at build time). Writes demo/register.html --
gitignored, since it's ~2MB of embedded data derived from the warehouse; see
docs/DECISIONS.md for why the browser is a rebuilt-on-purpose static
snapshot, not a live view.
"""

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from scripts.export_snapshot import export_coverage, export_entities, export_releases  # noqa: E402

DATABASE = ROOT / "data/warehouse.duckdb"
TEMPLATE = ROOT / "demo/register_template.html"
FONT = ROOT / "demo/assets/Fraunces-Variable.ttf"
OUTPUT = ROOT / "demo/register.html"


def build() -> Path:
    if not DATABASE.exists():
        raise FileNotFoundError(f"{DATABASE} does not exist. Run scripts/rebuild.py first.")
    if not FONT.exists():
        raise FileNotFoundError(f"{FONT} is missing -- it's a committed asset, not fetched at build time.")

    template = TEMPLATE.read_text()
    font_b64 = base64.b64encode(FONT.read_bytes()).decode()

    with duckdb.connect(str(DATABASE), read_only=True) as connection:
        releases_b64 = export_releases(connection)
        entities_b64 = export_entities(connection)
        coverage_json = export_coverage(connection)

    html = (
        template
        .replace("__FRAUNCES_B64__", font_b64)
        .replace("__RELEASES_B64__", releases_b64)
        .replace("__ENTITIES_B64__", entities_b64)
        .replace("__COVERAGE_JSON__", coverage_json)
    )
    OUTPUT.write_text(html)
    return OUTPUT


def main() -> None:
    output = build()
    print(f"wrote {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
