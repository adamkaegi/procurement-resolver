# Project Status

What this project is right now, not a log of how it got here — the session
history lives in `git log` if it's ever needed. Rationale for any individual
choice below is in `docs/DECISIONS.md`; specific resolution failure modes
are in `docs/FAILURES.md`.

## Ingestion and the warehouse

Six sources across federal, Ontario, and City of Ottawa procurement,
ingested through a single reproducible command:

```
uv run python scripts/rebuild.py
```

which reads only already-archived raw payloads under `data/raw/` (no
network calls), applies each source's mapping or extractor, validates every
record against `schema/ocds_subset.json`, loads the warehouse, and rebuilds
the resolution layer. Three full-table hash comparisons across independent
rebuilds confirm it's deterministic (output is byte-identical run over run,
aside from the legitimately-varying fetch timestamp).

| Source | Jurisdiction | Format | Records | Disclosure threshold |
|---|---|---|---:|---:|
| `federal_contracts` | Federal | CSV | 5,000 | $10,000 |
| `canadabuys_award_notices` | Federal | CSV | 5,000 | $10,000 |
| `canadabuys_contract_history` | Federal | CSV | 5,000 | $10,000 |
| `ontario_vor` | Ontario | CSV | 1,822 | $25,000 |
| `ottawa_contracts_awarded` | Ottawa | PDF (2023–) | 2,701 | $25,000 |
| `ottawa_historical_contracts` | Ottawa | Excel (2020–2022) | 3,903 | $25,000 |

**23,426 records** total, each with a full provenance block
(`_provenance.source_id`, `fetched_at`, `mapping_version`, `raw_ref`,
`field_origins`) and an `extraction_conf` on every document-extracted
record. Every source's `known_gaps` — what it structurally can't see, not
just what row count it has — is in the `coverage` table alongside its
disclosure threshold and archived date range; that table is what lets the
agent attach a real caveat instead of a generic one.

Two of the three federal CSV sources (`federal_contracts`,
`canadabuys_award_notices`) load only the first 5,000 rows of much larger
files (~1.39M and ~786K rows respectively) — the volume cap the project
scopes to, applied in file order rather than as a random sample. Noted in
each source's `coverage.known_gaps`, not hidden in the row count alone.

Field mapping for three of the four CSV sources is hand-written and
reviewed (`sources/*/mapping.yaml`); the fourth
(`canadabuys_contract_history`) is real, unedited output from a
locally-running Ollama model (`qwen2.5:7b-instruct`) — see
`docs/DECISIONS.md` for what that run actually looked like, including its
real quality gaps. Ottawa's two sources are extracted by dedicated code
(`src/extract_documents.py` for PDFs, `src/ingest_ottawa_open_data.py` for
Excel workbooks) rather than mapping config; `docs/DECISIONS.md` covers why
mapping application is code-driven rather than `mapping.yaml`-driven
throughout.

## Vendor resolution

Deterministic normalization (legal-suffix stripping, punctuation, casing) +
blocking + `rapidfuzz` scoring, per spec Part 8. Current warehouse: **9,030
resolved entities**, **23,426 entity links**, of which **412 entities
resolve to records in two or more jurisdictions** — vendors genuinely
visible across levels of government that would otherwise look like
unrelated records in three separate CSVs. Stantec Consulting Ltd is the
largest, with 129 linked contracts across all three jurisdictions.

Entity links currently persisted are exact-normalized matches only
(confidence 1.0). Fuzzy and uncertain-band candidates are scored live by
`resolve.rank_candidates` (what `resolve_vendor` surfaces) but aren't
written to `entity_link`. The scoring function's known precision limit —
`token_set_ratio` treats a name that's a strict token superset of another as
a full match regardless of meaning — is catalogued as `docs/FAILURES.md`
#17 and left visible in `resolve_vendor` output rather than filtered out.

## MCP agent

Five typed tools (`src/agent_tools.py`, wired in `src/server.py`), no
`run_sql`, each returning a pydantic model: `resolve_vendor`,
`entity_profile`, `cross_level_exposure`, `compare_buyers`, `coverage`.
Refusal logic is rule-based and verified against the live warehouse, not
just fixtures — e.g. `cross_level_exposure` on a multi-jurisdiction vendor
returns a real per-jurisdiction breakdown; on a single-jurisdiction vendor
it declines with a stated reason instead of fabricating a cross-level
total. Connect any MCP client (Claude Desktop config and a scripted demo
pairing a confident answer with a correct refusal): `docs/AGENT_DEMO.md`.

## Data browser

A static, filterable snapshot of the full warehouse — every record, every
cross-jurisdiction resolved entity, the same coverage caveats the MCP tools
return — published via GitHub Pages
([link in the README](../README.md#try-it)). Built by
`scripts/build_register.py` (which reuses `scripts/export_snapshot.py`'s
data-fragment functions) and pushed to the `gh-pages` branch; no server, no
live database connection at runtime.

## Tests and CI

`uv run pytest` — 75 tests, deterministic, no network, no model call, run
in CI on every push (`.github/workflows/ci.yml`). `uv run ruff check .`
clean throughout.

## What isn't measured, by decision

This project's own thesis is that a claim needs a number behind it, so this
is stated plainly once rather than hedged throughout: field-mapping
precision/recall, resolution precision/recall, and agent refusal-rate are
**not measured, and won't be** — a formal hand-labelled evaluation set was
scoped out (`docs/SPEC.md` Part 3), not left half-finished. Reliability is
demonstrated a different way instead: every mapping and resolution decision
is logged and reviewable, specific failure modes are catalogued with root
causes (`docs/FAILURES.md`), and the agent's confident-answer/correct-refusal
behavior is verified live against the real warehouse (`docs/AGENT_DEMO.md`)
rather than scored against a held-out question set. No precision, recall,
cost, or latency figure is reported anywhere in this repo that didn't come
from an actual eval or log run — see `evals/results/` for what has.
