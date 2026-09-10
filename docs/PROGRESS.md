# Progress

## Phase 0

- Acceptance test: fetched the official archived CanadaBuys OCDS pilot records ZIP and validated every English `compiledRelease` against `schema/ocds_subset.json`.
- Result: passed for 250 releases.
- Decision: the pilot's outer package envelope is not the canonical record; validation targets `records[*].compiledRelease`.
- Uncertainty: the subset intentionally permits additional OCDS fields because the pilot contains publisher, tender, planning, and document fields outside the project subset.
- Human verification before Phase 1: confirm the deliberate permissiveness of `additionalProperties` remains appropriate when manual adapters are reviewed.

## Phase 1

- Acceptance test: fetched the three verified source CSVs, applied hand-written YAML mappings, validated canonical records, loaded DuckDB, and queried all sources with provenance.
- Result: passed with 5,000 federal contract records, 5,000 CanadaBuys award records, and 39 populated Ontario VOR records. The source cap was applied before transformation.
- Decisions: CanadaBuys negative amendment amounts use its published total contract value; Ontario `TBD` start dates use the published tender-posting date; Ontario notes/footer rows without a VOR number are excluded.
- Uncertainty: the Ontario VOR outlook is a planned-opportunity source rather than an award ledger and publishes no award value; its canonical amount is therefore deterministic zero and must remain a documented coverage limitation.
- Human verification before Phase 2: review all three mappings against the archived raw headers and confirm the Ontario source is suitable for the intended gold-set scope.

## Phase 3

- Acceptance test: generated provisional mappings for all three Phase 1 sources, compared their field surfaces with the hand-written mappings, and generated a held-out CanadaBuys contract-history mapping whose sample records passed the canonical validation gate.
- Result: passed as an offline pipeline scaffold. The comparison was measurable but used only provisional data and is invalid for reporting.
- Instrumentation: each generation logged input/output tokens, cost, latency, retries, and validation outcome in `evals/results/PROVISIONAL_*.log`; the offline generator correctly records zero model tokens and zero model cost because no model endpoint is configured.
- Decision: the generator abstains when a field-name match is not unambiguous and uses a fixed transform registry; no external LLM call was fabricated.
- Uncertainty: this proves the contract and gate, not LLM mapping quality. A human must replace the provisional set under `evals/gold/` before any metric is reported.
- Human verification before the next phase: inspect the held-out mapping and decide which model provider and cost schema should replace the offline proposal engine.

## Phase 4

- Acceptance test: not run because the required Ottawa source could not be verified for both usable retrieval and licence.
- Result: blocked after a capped attempt. The official City of Ottawa pages returned an Incapsula anti-bot challenge; the reachable third-party meeting host did not expose a verifiable open-data licence.
- Decision: no substitute source was used, and no Ottawa document was downloaded or sent to an extraction model.
- Uncertainty: the underlying reports may still be publicly available through the meeting host, but their reuse terms remain unverified.
- Human verification before the next phase: determine whether the City can provide a directly licensed report archive or written reuse permission.

## Phase 5

- Acceptance test: evaluated the single-path provisional pair file with deterministic normalized-name blocking and rapidfuzz scoring, reporting precision and recall with absolute counts by jurisdiction pair; built the `entity`, `entity_link`, and `coverage` DuckDB tables.
- Result: passed on provisional scaffolding only. The detailed counts and percentages are in `evals/results/PROVISIONAL_resolution_metrics.log` and are invalid for reporting.
- Instrumentation: the uncertain score band, adjudicated-pair count, adjudication proportion, and cost placeholder are logged; without a configured model adjudicator, uncertain pairs abstain rather than being forced into a match.
- Decisions: entity links preserve verbatim source vendor names; exact-normalized clusters use `vendor_to_vendor` mode; no registry identifiers or Ottawa source records were fabricated after Phase 4 was blocked.
- Uncertainty: the provisional pairs are model-generated and the warehouse contains only federal and Ontario source records, so no production resolution claim is supported.
- Human verification before the next phase: replace the provisional pair path with `evals/gold/resolution/pairs.csv` after hand labelling, then review entity links and coverage gaps before building agent tools.