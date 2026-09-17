# Runbook — how this project was actually built

The build methodology, kept for the parts that aren't obvious from the
result: the discipline each phase was run under, and the audit that ran
between them. The phase list and acceptance tests themselves live in
[`docs/SPEC.md`](SPEC.md) Part 10 — this file doesn't restate them.

For what exists today, see [`README.md`](../README.md) and
[`docs/PROGRESS.md`](PROGRESS.md).

## The rules the build ran under

**One phase per session.** Never chain phases in a single run. Each
acceptance test is a place where a silent wrong turn becomes visible, and a
context seven phases deep will have forgotten why the schema looks the way
it does.

**Every phase commits.** So anything can be reverted, and the diff at each
acceptance test is reviewable on its own.

**Verify sources before writing an adapter.** Confirm the URL is live and
record the licence in `source.yaml` first. If a URL 404s or the licence is
unclear, stop and report — never substitute a similar-looking source.

**Hard stops are real.** Phase 4 (Ottawa document extraction) was the
designated highest-risk phase and was run with an explicit cap: if
extraction wasn't producing validating records after a reasonable effort,
stop and document exactly what defeated it. A documented failure was an
acceptable outcome; shipping two levels instead of three was acceptable.
Unbounded effort was not.

**Gold-set work was human-only, then cut.** Phase 2 was originally a
scored evaluation set built by hand, which every later percentage would
have been measured against. It was cut from scope — see `docs/SPEC.md`
Part 3. Phases 3, 5, and 6 were adjusted accordingly: reproducibility and
live-demonstrated behavior in place of precision/recall/refusal-rate.

## Human review, per phase

The checks that needed a person, not the agent that wrote the code:

- **Schema (Phase 0)** — does the OCDS subset match spec Part 5? Did it
  actually fetch the pilot data, or invent a schema and assert success?
- **Mappings (Phase 1)** — open every `mapping.yaml` and read it against
  the raw headers. The cheapest place to catch a misunderstanding of the
  schema.
- **Extraction (Phase 4)** — spot-check ten extracted records against the
  source PDFs. Extraction is where silent corruption is most likely and
  least visible.
- **Resolution (Phase 5)** — read the hard cases in `docs/FAILURES.md`
  against what the resolver actually did with them.

## Between phases

Read `docs/PROGRESS.md` and look specifically for:

- acceptance tests that were quietly weakened to pass
- sources substituted without a flag
- any number that appeared somewhere without a real run behind it
- claims about the data asserted rather than measured

The failure mode of autonomous runs is not sabotage. It's something
reasonable and wrong, reported confidently.
