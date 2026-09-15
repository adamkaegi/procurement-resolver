"""MCP server exposing the five typed procurement-resolution tools (spec Part 9).

No run_sql tool (CLAUDE.md rule 5). Every tool call opens a fresh read-only
DuckDB connection against data/warehouse.duckdb -- this server never writes
to the warehouse, and coexists with other local DuckDB clients (e.g. the
duckdb CLI) that might have it open at the same time.

Run directly for local testing:
    uv run python -m src.server

Or point an MCP client (e.g. Claude Desktop) at it via stdio -- see
docs/AGENT_DEMO.md for the client config snippet and a scripted demo.
"""

from pathlib import Path

import duckdb
from fastmcp import FastMCP

from . import agent_tools as tools

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data/warehouse.duckdb"

mcp = FastMCP(
    "procurement-resolver",
    instructions=(
        "Answers questions about federal, Ontario, and City of Ottawa procurement "
        "contracts resolved into one warehouse. Every tool that touches a resolved "
        "vendor entity returns a confidence score; every tool that aggregates "
        "across sources returns coverage caveats and can decline to aggregate. "
        "Federal, Ontario, and Ottawa disclose contracts above different dollar "
        "thresholds -- call `coverage` before treating any cross-jurisdiction "
        "comparison as apples-to-apples, and prefer declining over guessing when "
        "resolution confidence or coverage doesn't support a claim."
    ),
)


def _connect() -> duckdb.DuckDBPyConnection:
    if not DATABASE.exists():
        raise FileNotFoundError(f"{DATABASE} does not exist. Run `uv run python scripts/rebuild.py` first.")
    return duckdb.connect(str(DATABASE), read_only=True)


@mcp.tool()
def resolve_vendor(name: str, jurisdiction: str | None = None) -> tools.ResolveVendorResult:
    """Resolve a vendor name to ranked candidate entities with confidence and evidence.

    jurisdiction, if given, must be one of "federal", "on", "ottawa" and
    restricts candidates to entities with at least one link in that jurisdiction.
    """
    with _connect() as connection:
        return tools.resolve_vendor(connection, name, jurisdiction)


@mcp.tool()
def entity_profile(entity_id: str) -> tools.EntityProfileResult | None:
    """Return everything known about a resolved entity: every source-verbatim
    vendor name it's linked to (with per-link confidence and method), and every
    contract found under those names across all three jurisdictions. Returns
    null if entity_id doesn't exist -- get entity_id from resolve_vendor first.
    """
    with _connect() as connection:
        return tools.entity_profile(connection, entity_id)


@mcp.tool()
def cross_level_exposure(entity_id: str) -> tools.CrossLevelExposureResult | None:
    """Total contract exposure for a resolved entity, broken out by jurisdiction.

    Declines to produce a combined figure (declined=true, decline_reason set)
    when the entity resolves to only one jurisdiction, or when the weakest
    entity-link confidence backing it falls below the aggregation floor.
    Sources that publish no per-transaction value (e.g. Ontario VOR arrangements)
    are excluded from dollar totals and flagged with amount_caveat, never
    silently treated as zero spend. Returns null if entity_id doesn't exist.
    """
    with _connect() as connection:
        return tools.cross_level_exposure(connection, entity_id)


@mcp.tool()
def compare_buyers(jurisdictions: list[str], category: str | None = None) -> tools.CompareBuyersResult:
    """Compare top buyers by contract total within the given jurisdictions
    ("federal", "on", "ottawa"). category is an optional, best-effort
    case-insensitive substring filter over award descriptions -- there is no
    reliable shared commodity taxonomy across the three sources, so treat
    matches as a heuristic, not a category system.

    Always returns coverage caveats (differing disclosure thresholds across
    jurisdictions make these differently-censored populations, not a
    like-for-like comparison). Declines to report a per-buyer total when fewer
    than 3 matching records back it, returning the count instead.
    """
    with _connect() as connection:
        return tools.compare_buyers(connection, jurisdictions, category)


@mcp.tool()
def coverage(jurisdiction: str | None = None, date_start: str | None = None, date_end: str | None = None) -> tools.CoverageResult:
    """What this warehouse actually holds: per-source jurisdiction, archived
    date range, disclosure value_threshold, record_count, and known_gaps
    (the caveats a human already wrote down about that source's limits).

    date_start/date_end (ISO date strings) are optional; if given, returns a
    caveat for any source whose archived date range doesn't cover the request.
    This is the tool to call before trusting any other tool's aggregate.
    """
    with _connect() as connection:
        return tools.coverage(connection, jurisdiction, date_start, date_end)


if __name__ == "__main__":
    mcp.run()
