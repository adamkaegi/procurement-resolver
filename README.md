# Cross-Jurisdictional Procurement Resolver

[![CI](https://github.com/adamkaegi/procurement-resolver/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/adamkaegi/procurement-resolver/actions/workflows/ci.yml)

Canadian public procurement is published at three levels of government —
federal, Ontario, and the City of Ottawa — sharing no schema, no vendor
identifier, and no common format. A firm holding contracts at all three is
invisible as a single entity to every existing system. Worse, each level
discloses above a different dollar threshold, so even "total spend"
compares differently-censored populations unless something says so.

Two things here:

1. **An adapter layer** — six sources into one canonical schema (a subset of
   [OCDS 1.1](https://standard.open-contracting.org/)), with
   cross-jurisdictional vendor resolution on top.
2. **An MCP agent** — five typed tools, no free-text SQL — that answers
   cross-level questions with resolution confidence attached, and declines
   rather than guesses when the data can't support a claim.

The domain is a corpus, not the point: the same shape appears consolidating
ERPs after an acquisition, joining claims across carriers, or reconciling
provider registries. Full rationale: [`docs/SPEC.md`](docs/SPEC.md).

## Try it

- **[The Register](https://adamkaegi.github.io/procurement-resolver/)** — a
  filterable browser over the whole warehouse: every contract, every vendor
  resolved across jurisdictions, and the same coverage caveats the tools
  return. No setup required.
- **The MCP agent**, against your own machine — see
  [Connecting an MCP client](#connecting-an-mcp-client).

## What it looks like

Three unedited sessions driving the local MCP server from Claude Desktop —
no extra code, no hosting, no auth ([setup](docs/AGENT_DEMO.md)). Click any
image for full size.

<p align="center">
  <a href="docs/images/mcp-entity-profile-deloitte.png">
    <img src="docs/images/mcp-entity-profile-deloitte.png" width="720"
         alt="An MCP client showing an entity_profile result for Deloitte: five source-verbatim vendor spellings folded into one entity across five sources, per-jurisdiction exposure, and a section listing what was deliberately excluded from the totals and why.">
  </a>
</p>

**The evidence, including what isn't counted.** Five spellings
(`DELOITTE INC`, `DELOITTE LLP`, `Deloitte`, …) resolve to one entity across
three jurisdictions. Then: six Ontario VOR records held out of any dollar
total, one candidate link persisted at `0.696` and excluded until
adjudicated, two weaker near-matches left as separate entities. Nothing
silently merged, nothing uncertain silently counted.

<p align="center">
  <a href="docs/images/mcp-coverage-caveats-deloitte.png">
    <img src="docs/images/mcp-coverage-caveats-deloitte.png" width="720"
         alt="An MCP client answering which level of government spends more with Deloitte: federal $72.7M versus Ottawa $21.0M, followed by five caveats explaining why the two figures are not directly comparable.">
  </a>
</p>

**Caveats, unprompted.** It answers the comparison, then explains why the
answer shouldn't be trusted as stated: different disclosure thresholds
($10K federal, $25K Ottawa), different coverage windows, and the fact that
the largest federal source contributes no high-confidence links here at
all.

<p align="center">
  <a href="docs/images/mcp-declined-kleenoil.png">
    <img src="docs/images/mcp-declined-kleenoil.png" width="720"
         alt="An MCP client relaying a declined cross_level_exposure result for Kleenoil Filtration Canada Ltd, which resolves in only one jurisdiction, with the per-source Ottawa detail returned instead of a fabricated cross-level total.">
  </a>
</p>

**The refusal.** One jurisdiction can't support a cross-level claim, so it
declines and says why — returning the Ottawa detail rather than a
fabricated total. Underneath, that's a typed response the client renders:

```jsonc
{
  "canonical_name": "KLEENOIL FILTRATION CANADA LTD",
  "declined": true,
  "decline_reason": "This entity currently resolves to records in only 1 jurisdiction(s). Cross-level exposure requires more than one to be meaningful; returning per-source detail instead of a cross-level total.",
  "exposures": [
    { "jurisdiction": "ottawa", "source_id": "ottawa_contracts_awarded",
      "contract_count": 2, "total_amount": 333035.45 },
    { "jurisdiction": "ottawa", "source_id": "ottawa_historical_contracts",
      "contract_count": 1, "total_amount": 168689.0 }
  ]
}
```

Confidence and coverage caveats ride along on every answer; where they
can't support a claim, the tool says so rather than guessing.

*The `ent_…` ids in these sessions are content-hashed from the build they
were captured against; a rebuild can produce different ids for the same
firms.*

## Architecture at a glance

```
data/raw/<source>/<timestamp>/   archived raw payloads, immutable, never re-fetched
        │
        ▼
apply_mapping.py / extract_documents.py / ingest_ottawa_open_data.py
        │            (deterministic; each mapping.yaml is executed by a generic interpreter)
        ▼
validate.py            (every record checked against schema/ocds_subset.json)
        ▼
load.py                → data/warehouse.duckdb : releases
        ▼
resolve.py              token blocking → rapidfuzz scoring → confidence bands
        ▼
                        → entity, entity_token, entity_link, coverage
        ▼
agent_tools.py + server.py   five typed MCP tools, confidence + coverage
                              caveats on every answer, refusal below threshold
```

Single-file DuckDB, no server, no Docker, no cloud infrastructure — see
[`CLAUDE.md`](CLAUDE.md) for the full set of rules this repo is built under
(source immutability, no fabricated metrics, no `run_sql` tool, etc.), which
override the usual defaults throughout this codebase.

| Layer | Where |
|---|---|
| Canonical schema | `schema/ocds_subset.json` |
| Per-source config (fetch, licence, mapping) | `sources/<source_id>/` |
| Pipeline code | `src/` |
| Warehouse (gitignored, rebuildable) | `data/warehouse.duckdb` |
| MCP server + tools | `src/server.py`, `src/agent_tools.py` |
| Tests (code correctness) | `tests/` |
| Evals (model/pipeline behaviour) | `evals/` |
| Decision log / progress / known failures | `docs/` |

## Setup and running locally

Requires Python 3.11 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                          # install dependencies into .venv
uv run python scripts/rebuild.py # rebuild data/warehouse.duckdb from data/raw/ (no network)
uv run pytest                    # deterministic code-path tests, no network, no model
uv run ruff check .              # lint
```

`rebuild.py` is the reproducibility path: archived raw payloads in →
validated warehouse and resolution tables out, no network calls and no
model.

`data/raw/` is not committed (source payloads are archived locally and not
redistributed — [`CLAUDE.md`](CLAUDE.md) rule 2), so the full rebuild needs
a machine that has them. **From a cold clone:** `uv sync` and `uv run
pytest` work immediately (two tests needing archived data skip themselves,
same as CI), plus the published site above. Each source's download URL and
licence are in `sources/<source_id>/source.yaml`; `src/fetch.py` is the
archival helper.

### Connecting an MCP client

No bespoke UI on purpose — any MCP client drives `src/server.py` directly.
Config and a scripted demo: **[`docs/AGENT_DEMO.md`](docs/AGENT_DEMO.md)**.

The five tools (`src/agent_tools.py`, wired in `src/server.py`):

| Tool | Returns |
|---|---|
| `resolve_vendor(name, jurisdiction?)` | ranked entity candidates with confidence and evidence |
| `entity_profile(entity_id)` | every contract behind a resolved entity, across jurisdictions |
| `cross_level_exposure(entity_id)` | totals by jurisdiction — declines below a confidence/coverage floor |
| `compare_buyers(jurisdictions, category?)` | buyer aggregates with threshold caveats attached |
| `coverage(jurisdiction?, date_range?)` | what the warehouse actually holds, and its known gaps |

No `run_sql` tool — typed tools only, per `CLAUDE.md` rule 4.

## Status

**6 sources, 23,426 records.** End-to-end rebuild in ~45s. 8,916 resolved
entities, 483 spanning two or more jurisdictions, with the uncertain match
band persisted separately and excluded from every total until adjudicated.
A working MCP server with refusal logic verified against live data, and a
real logged local-LLM mapping-generation run
([`llm_calls.jsonl`](evals/results/llm_calls.jsonl)).

- [`docs/PROGRESS.md`](docs/PROGRESS.md) — what exists now, in detail
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — every design choice with its
  rejected alternative
- [`docs/FAILURES.md`](docs/FAILURES.md) — defects and hard cases found in
  the real data, with root causes

**Not measured, by decision:** mapping precision/recall, resolution
precision/recall, and agent refusal-rate. A scored evaluation set was cut
from scope ([`docs/SPEC.md`](docs/SPEC.md) Part 3), so no such figure is
claimed anywhere — the decision log, failure catalogue, and demos above are
what stand in for it.

## License

Code is MIT — see [`LICENSE`](LICENSE). The underlying government data is
**not** redistributed here (`data/raw/` is gitignored) and stays under its
own source licence; see `licence` / `licence_url` in each
`sources/<source_id>/source.yaml`.
