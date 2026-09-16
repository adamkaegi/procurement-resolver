# Runbook — Autonomous build sequence

> The methodology this project was actually built under, with one
> deliberate exception: Phase 2 (hand-labelled evaluation sets) was later
> decided against outright, and the phases that depended on it are updated
> here to say so rather than silently going stale. For what exists today,
> see [`README.md`](../README.md) and [`docs/PROGRESS.md`](PROGRESS.md).

One phase per session. Do not chain phases in a single run: each acceptance test
is a place where a silent wrong turn becomes visible, and a compacted context
seven phases deep will have forgotten why the schema looks the way it does.

## Before anything

```
mkdir procurement-resolver && cd procurement-resolver
git init
mkdir -p docs
cp /path/to/spec.md docs/SPEC.md
cp /path/to/CLAUDE.md .
git add -A && git commit -m "spec and guardrails"
```

Run in a container or VM with scoped filesystem access. Every phase commits, so
anything can be reverted.

---

## Phase 0 — Foundations

> Read docs/SPEC.md and CLAUDE.md in full.
>
> Implement Phase 0 only. Scaffold the repo per spec Part 6, pin dependencies,
> and write schema/ocds_subset.json.
>
> Acceptance test: fetch the archived CanadaBuys OCDS pilot dataset and validate
> it against your subset schema. It must pass. If it fails, the subset is wrong
> — fix the subset, not the data.
>
> Before writing the schema, verify the pilot dataset is still reachable. If it
> is not, stop and report rather than substituting another source.
>
> Stop when the acceptance test passes. Append to docs/PROGRESS.md and commit.

**Your review:** does the OCDS subset match spec Part 5? Did it actually fetch
the pilot data, or did it invent a schema and assert success?

---

## Phase 1 — Manual adapters

> Implement Phase 1 only. Hand-write mapping.yaml for three sources: federal
> proactive disclosure over $10K, CanadaBuys award notices, and one Ontario
> source from spec Part 4.
>
> Do NOT build the mapping generator. Do not use an LLM to produce these
> mappings — write them by reading the data. The point is to learn the failure
> modes before automating.
>
> Verify each source URL is live and record its licence in source.yaml first.
> Cap each source at 5,000 records.
>
> Acceptance test: all three ingest, validate, and load to DuckDB; one SQL query
> returns records from all three with the full provenance block populated.

**Your review:** open all three `mapping.yaml` files and read them against the
raw data yourself. This is your calibration for Phase 2, and it's the cheapest
place to catch a misunderstanding of the schema.

---

## Phase 2 — Skipped by decision

Originally: a full day of hand-labelling held-out mapping corrections,
~200 vendor-resolution pairs, and 40 agent questions, so every later
percentage would have a real baseline. Decided not to spend it — see
`docs/SPEC.md` Part 3, "Explicitly out of scope." Phases 3, 5, and 6 below
were adjusted accordingly: reproducibility and live-demonstrated behavior
in place of precision/recall/refusal-rate against a held-out label set.

---

## Phase 3 — Mapping generator

> Implement Phase 3 only. Build src/generate_mapping.py, the transform registry,
> and the validation gate per spec Part 7.
>
> Acceptance test: the generator reproduces the three Phase 1 hand-written
> mappings at a measurable rate, and produces a validating mapping for one
> held-out source with zero human edits. Log tokens, cost, and latency for every
> generation.

---

## Phase 4 — Ottawa document extraction — HARD STOP

> Implement Phase 4 only. Build src/extract_documents.py against City of Ottawa
> Delegation of Authority reports.
>
> HARD LIMIT: if extraction is not producing validating records after a
> reasonable effort, STOP. Write docs/BLOCKED.md describing exactly what
> defeated it — document structure, table layout, whatever. Do not spend
> unbounded effort here.
>
> A documented failure is an acceptable outcome for this phase and is a useful
> finding for the writeup. Shipping two levels instead of three is fine.
>
> Acceptance test: extracted records validate, carry _provenance.extraction_conf,
> and per-document cost is logged separately from mapping cost.

**Your review:** spot-check ten extracted records against the source PDFs
yourself. Extraction is where silent corruption is most likely and least visible.

---

## Phase 5 — Resolution

> Implement Phase 5 only. Build src/resolve.py per spec Part 8, plus the entity
> store and the coverage table.
>
> Deterministic blocking and rapidfuzz for the bulk; LLM adjudication only in
> the uncertain band. Log the band width and the proportion of pairs adjudicated.
>
> Link, never merge. Source vendor names are never rewritten.
>
> Acceptance test: the entity/entity_link/coverage tables build end-to-end;
> adjudication band width and proportion of pairs adjudicated are logged. No
> hand-labelled pair set exists (spec Part 3 scope cut), so no precision/recall
> figure is reported here.
>
> While building, maintain docs/FAILURES.md — every genuinely hard case you hit
> with its root cause. Target the categories in spec Part 8.

---

## Phase 6 — MCP server and agent

> Implement Phase 6 only. Build src/server.py with the five typed tools from
> spec Part 9 and the refusal logic.
>
> No run_sql tool. Every entity-touching tool returns resolution confidence;
> every aggregating tool returns coverage caveats.
>
> Acceptance test: the MCP server's typed tools are live against the real
> warehouse, and one session demonstrates a confident cross-level answer
> alongside a correct refusal. No hand-labelled agent-question set exists
> (spec Part 3 scope cut), so no refusal-rate percentage is reported here.

---

## Phase 7 — Gating sweep

> Implement Phase 7 only. Sweep the resolution confidence threshold and report
> how the auto-accept / adjudication-band / auto-reject split moves, with a
> spot-check of a sample from each band.
>
> Acceptance test: produce a sentence of the form "raising the auto-accept
> threshold from X to Y moved N pairs from auto-accepted to adjudicated", with
> the numbers coming from evals/results/. No hand-labelled set to score a
> silent-error curve against (spec Part 3 scope cut).
>
> Then write docs/FINDINGS.md: every metric produced, the ten-plus entries from
> docs/FAILURES.md with root causes, and the full ADR log. Facts only, no
> narrative framing.

**The writeup is yours.** Claude produces FINDINGS.md; you write WRITEUP.md from
it. The writeup is a judgment artifact — what the failure meant, which tradeoff
mattered, why the domain generalizes. It's also the thing you'll be asked about
in an interview, so it has to be yours.

---

## Between phases

Read `docs/PROGRESS.md`. Look specifically for:
- acceptance tests that were quietly weakened to pass
- sources substituted without a flag
- any number that appeared somewhere without an eval run behind it

The failure mode of autonomous runs is not sabotage. It's something reasonable
and wrong, reported confidently.
