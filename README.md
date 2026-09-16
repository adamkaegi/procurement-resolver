# Cross-Jurisdictional Procurement Resolver

Canadian public procurement is published at three levels of government — federal,
Ontario, and the City of Ottawa — that share no schema, no vendor identifier, and
no common publication format. A firm holding contracts at all three levels is
invisible as a single entity to every existing system, and the three levels
disclose contracts above three different dollar thresholds, so even a "total
spend" question is comparing differently-censored populations unless something
says so.

This repo builds two things:

1. **An adapter layer** that ingests federal, Ontario, and City of Ottawa
   procurement data into one canonical schema (a deliberate subset of
   [OCDS 1.1](https://standard.open-contracting.org/)), with mapping
   configs reviewed per source and cross-jurisdictional vendor resolution on top.
2. **An MCP agent** — five typed tools, no free-text SQL — that answers
   cross-jurisdictional questions over the resolved data with resolution
   confidence attached, and is built to decline rather than guess when the
   underlying resolution or coverage can't support a claim.

The domain is a corpus, not the point. The same shape shows up consolidating
ERPs after an acquisition, joining insurance claims across carriers, or
reconciling provider registries across hospital systems: different
vocabularies for the same entities, no common key, and a deadline. Full
framing and design rationale: [`docs/SPEC.md`](docs/SPEC.md).

## Try it

- **[The Register](https://claude.ai/code/artifact/1ad22cdc-4a5a-4e58-87ce-b7f0a6428ef7)**
  — a static, filterable browser over the resolved warehouse: every ingested
  contract, plus every vendor resolved across two or more jurisdictions, with
  the same coverage caveats the MCP tools return. No setup required.
- **The MCP agent**, from your own machine, talking to a real MCP client
  (e.g. Claude Desktop) — see [Connecting an MCP client](#connecting-an-mcp-client) below.

## Architecture at a glance

```
data/raw/<source>/<timestamp>/   archived raw payloads, immutable, never re-fetched
        │
        ▼
apply_mapping.py / extract_documents.py / ingest_ottawa_open_data.py
        │            (deterministic; CSV → mapping.yaml, PDF/XLSX → code-driven parse)
        ▼
validate.py            (every record checked against schema/ocds_subset.json)
        ▼
load.py                → data/warehouse.duckdb : releases
        ▼
resolve.py              blocking → rapidfuzz scoring → confidence bands
        ▼
                        → entity, entity_link, coverage
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

`scripts/rebuild.py` is the one-command reproducibility path: it reads only
the already-archived raw payloads under `data/raw/`, applies each source's
mapping/extraction, validates every record, loads the warehouse, and rebuilds
the `entity` / `entity_link` / `coverage` tables. It makes no network calls
and calls no model.

`data/raw/` itself is not checked into this repository (see
[`CLAUDE.md`](CLAUDE.md) rule 3 — source payloads are archived locally and
never re-fetched or modified in place). Rebuilding from a clean clone
requires re-fetching each source per `sources/<source_id>/source.yaml`
first, via `src/fetch.py`.

### Connecting an MCP client

The agent has no bespoke UI on purpose — any MCP client can drive
`src/server.py` for free, and a general-purpose client is a more convincing
demo than a one-off chat widget. Full walkthrough, exact Claude Desktop
config, and a scripted example pairing a confident answer with a correct
refusal in one session: **[`docs/AGENT_DEMO.md`](docs/AGENT_DEMO.md)**.

Quick reference, the five tools (`src/agent_tools.py`, wired in `src/server.py`):

| Tool | Returns |
|---|---|
| `resolve_vendor(name, jurisdiction?)` | ranked entity candidates with confidence and evidence |
| `entity_profile(entity_id)` | every contract behind a resolved entity, across jurisdictions |
| `cross_level_exposure(entity_id)` | totals by jurisdiction — declines below a confidence/coverage floor |
| `compare_buyers(jurisdictions, category?)` | buyer aggregates with threshold caveats attached |
| `coverage(jurisdiction?, date_range?)` | what the warehouse actually holds, and its known gaps |

No `run_sql` tool — typed tools only, per `CLAUDE.md` rule 5.

## Status

6 sources ingested (23,426 records), a working end-to-end rebuild
(`scripts/rebuild.py`), a resolved entity/entity_link/coverage layer (9,030
entities, 412 of them resolved across two or more jurisdictions), a working
MCP server with real refusal logic verified against the live warehouse, and
a real logged local-LLM mapping-generation run in
[`evals/results/llm_calls.jsonl`](evals/results/llm_calls.jsonl). Full
detail: [`docs/PROGRESS.md`](docs/PROGRESS.md).

Every design decision — deterministic vs. LLM, and every architectural
trade-off — is logged with its rejected alternative in
[`docs/DECISIONS.md`](docs/DECISIONS.md). Specific, named vendor-resolution
failure modes (numbered companies, parent/subsidiary pairs, a real scoring
false positive) with root causes are in
[`docs/FAILURES.md`](docs/FAILURES.md).

This project's thesis is that a reliability claim needs a number behind it
(`CLAUDE.md` rule 1: no precision, recall, cost, or latency figure appears
anywhere unless an eval run produced it) — so stated plainly rather than
implied: mapping-quality precision/recall, resolution precision/recall, and
agent refusal-rate are not measured yet. They depend on `evals/gold/` —
hand-labelled mapping corrections, ~200 vendor-resolution pairs, and 40
agent questions — which is intentionally empty pending human labelling
(`docs/RUNBOOK.md`), and on `evals/run_eval.py`, which doesn't exist yet.

## License

Code in this repository is MIT-licensed — see [`LICENSE`](LICENSE). The
underlying government procurement data is **not** redistributed via this
repo (`data/raw/` is gitignored) and remains subject to its own source
licence in each case — see `licence` / `licence_url` in every
`sources/<source_id>/source.yaml`.
