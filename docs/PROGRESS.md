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

## Phase 4 resumed

- Acceptance test: downloaded Ottawa contracts-awarded PDFs were parsed into canonical records, deduplicated by contract ID across overlapping Transit and period reports, validated against the OCDS subset, and checked against ten representative source rows.
- Result: passed for the text-extractable report records. One Transit PDF is image-only and produced no deterministic rows; it remains an explicit extraction gap for a later OCR/model-assisted pass.
- Decisions: the raw filename with the incorrect 2022 end year is not renamed; the report text supplies the 2023 period. Currency parsing accepts both `$ amount` and `amount $` layouts. Duplicate contract IDs retain the richest record and all raw references.
- Uncertainty: the parser extracts text-based tables reliably enough for the current acceptance check, but descriptions and non-competitive rationales can be absent, and image-only documents need a separate extraction method.
- Human verification before gold sets: review the ten-record spot check and decide whether the image-only Transit report belongs in the held-out extraction scope.

## Phase 1 resumed: active Ontario VOR export

- Acceptance test: verified the official active VOR page and CSV export, archived the export, applied the updated manual mapping, validated the canonical records, and rebuilt the local DuckDB releases table.
- Result: passed with 1,822 active Ontario VOR arrangements, replacing the 39-row 2018-2020 planning outlook.
- Decisions: the active export's two-line preamble is skipped; padded headers are normalized; the Windows-1252 encoding is declared; qualified vendor is used for supplier name; arrangement dates populate contract period; award value remains zero because no transaction value is published.
- Uncertainty: active VOR arrangements are not individual awards and may represent standing agreements or volume-license arrangements; cross-source spend comparisons must not treat the zero amount as observed spend.
- Human verification before gold sets: decide whether the active arrangement registry belongs in the Ontario gold mapping scope or whether a separate Ontario award-notice source is needed.