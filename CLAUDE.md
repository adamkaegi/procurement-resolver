# CLAUDE.md — Cross-Jurisdictional Procurement Resolver

Read `docs/SPEC.md` before doing anything. It is the source of truth. This file
is the set of rules that override convenience.

> This is the actual rule set this project was built under, left as-written
> and still in force. For what the project currently is, see
> [`README.md`](README.md) and [`docs/PROGRESS.md`](docs/PROGRESS.md).

## What this project is

Two systems over Canadian procurement data (federal / Ontario / City of Ottawa):
an adapter layer with LLM-generated field mappings and cross-jurisdictional
vendor resolution, and an MCP agent that answers cross-level questions with
resolution confidence attached.

The deliverable is **measured reliability**, not a dataset. Every design choice
serves a number in the eval harness.

## Absolute rules

1. **Never fabricate a metric.** No precision, recall, cost, or latency figure
   appears in any file unless `evals/run_eval.py` produced it and wrote it to
   `evals/results/`. If asked to write a README or summary before the eval has
   run, use `TBD` — never a plausible placeholder.

2. **Source records are immutable.** Raw payloads under `data/raw/` are never
   modified after fetch. Vendor names are never normalized in place. Resolution
   writes to the `entity_link` table and points at source records.

3. **Verify before ingesting.** Confirm each source URL is live and record its
   licence in `source.yaml` before writing an adapter. If a URL 404s or the
   licence is unclear, STOP and report. Do not substitute a similar-looking
   source on your own initiative.

4. **No `run_sql` tool on the MCP server.** Typed tools only, per spec Part 9.

5. **Stop conditions are real.** If a phase's acceptance test fails twice, stop
   and write a failure report to `docs/BLOCKED.md`. Do not work around it, and
   do not loosen the acceptance test to make it pass.

## LLM usage policy

Per source, not per row — with one deliberate exception (Ottawa document
extraction, which is necessarily per document).

- Mapping generation: once per source, output committed as reviewable config.
- Applying mappings: deterministic code, no model calls.
- Normalization a regex or lookup table can do: use the regex or lookup table.
- Entity resolution: deterministic blocking + rapidfuzz for the bulk; LLM
  adjudication only in the uncertain confidence band.

Every LLM call logs tokens, cost, and latency to `evals/results/llm_calls.jsonl`.
This is a deliverable, not debug output.

Report federal/Ontario onboarding cost and Ottawa per-document extraction cost
**separately**. Never blend them — they are different economic regimes and
conflating them hides the finding.

## Decision log

Write an ADR entry in `docs/DECISIONS.md` every time you choose deterministic
logic over an LLM call, or vice versa. Format: context, decision, alternative
rejected, consequence. These entries are the source material for the writeup —
they are more valuable than the code.

## Stack

- Python 3.11+, `uv` for deps
- DuckDB only. Single file. No server, no Docker, no cloud infra.
- `rapidfuzz` for string similarity
- `pydantic` for the canonical model, JSON Schema for validation
- `fastmcp` for the MCP server
- `pytest` for tests
- `openpyxl` for Excel-workbook source extraction (added via ADR, `docs/DECISIONS.md`)

Do not add dependencies beyond these without writing an ADR.

## Conventions

- Type hints on everything. `ruff` clean before any commit.
- Commit at every acceptance test. Message format: `phase-N: <what passed>`.
- Tests live beside the eval harness, not inside it. Evals measure model
  behaviour; tests measure code correctness. Do not conflate them.
- Prefer boring code. This repo will be read by interviewers, not scaled.

## Reporting

`docs/PROGRESS.md` describes the project's current state — what's built and
what isn't — not a session-by-session log. At the end of every phase, update
it to stay accurate, rather than appending another entry to a growing diary.
Session-level detail (what an acceptance test checked, decisions made,
doubts raised) belongs in `git log` and, for anything that's a real
deterministic-vs-LLM or architectural choice, in `docs/DECISIONS.md`.

Be specific about uncertainty when it belongs in `docs/PROGRESS.md`'s "What
isn't measured yet" section — a flagged doubt there is more useful than a
confident summary. It does not need to be repeated everywhere else.
