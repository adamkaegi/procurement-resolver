# Gold sets — intentionally empty

This directory is empty on purpose, not by omission. Per `CLAUDE.md` rule 2
and `docs/RUNBOOK.md`'s Phase 2, these three sets are human-only labelling
work that Claude Code must never create, edit, or synthesize:

- `mappings/` — correct field mappings for two held-out sources
- `resolution/pairs.csv` — ~200 vendor pairs labelled match/no-match, spread
  across all three jurisdiction pairings
- `agent/questions.yaml` — 40 agent questions in three buckets (answerable,
  answerable-with-caveat, unanswerable)

They were never completed. Every mapping-quality, resolution, and agent
metric in this project depends on them and is reported as not-measured as
a result — see `docs/PROGRESS.md`, "What isn't measured yet." Labelling
after seeing model output would invalidate it, so this isn't a step that
can be caught up quietly; it has to happen before the systems it evaluates
are built, per `docs/RUNBOOK.md`.
