# Progress

## Source-scope expansion (2026-09-15)

Not a phase from `docs/SPEC.md` -- picked up at Adam's request to expand
source scope for the resume writeup, staying within federal/Ontario/Ottawa.
Full detail and reasoning in `docs/DECISIONS.md`, "Source-scope expansion" and
"`openpyxl` dependency and a `curl` fallback"; this is the durable summary.

- **What was added.** Two new sources, both verified live and licence-checked
  before writing an adapter (CLAUDE.md rule 4): `canadabuys_contract_history`
  (federal; PWGSC/PSPC's full contract-history CSV, OGL-Canada, distinct
  dataset from the existing `canadabuys_award_notices`) and
  `ottawa_historical_contracts` (Ottawa; 2020-2022 delegation-of-authority
  Excel workbooks, City of Ottawa Open Data Licence v2.0, extending Ottawa
  coverage backward from `ottawa_contracts_awarded`'s 2023-onward start with
  no date overlap by design). Sources: 4 -> 6. `releases`: 14,523 -> 23,426.
  `entity`: 6,392 -> 9,030. `entity_link`: 14,523 -> 23,426.
- **What was checked and rejected, not silently skipped.** Searched for a
  second Ontario source (ministry award notices / Broader Public Sector
  disclosure, the original spec's "Ontario ministry notices" gap) and for a
  1H-2020/2016-2019 Ottawa extension. Neither had a real, live, openly-
  licensed, structurally-consistent dataset behind it at the point this
  session stopped searching -- both are documented as deliberate scope cuts
  in `docs/DECISIONS.md`, not silent gaps. Ontario is still single-sourced.
  Ontario and municipality count were both explicitly out of scope per
  Adam's instruction (stay at 3 jurisdictions), so this was not attempted.
- **Acceptance check used.** `scripts/rebuild.py` end-to-end from archived
  raw payloads only (no network calls during rebuild), all 23,426 releases
  round-trip-validate against `schema/ocds_subset.json`, `coverage` picks up
  both new sources automatically with populated date ranges and known_gaps,
  `ruff check .` clean, `pytest` 73 passed (up from 68 -- added
  `tests/test_ingest_ottawa_open_data.py`, extended `tests/test_apply_mapping.py`).
  Smoke-tested `agent_tools.resolve_vendor`/`cross_level_exposure` directly
  against the rebuilt warehouse: "Kleenoil Filtration Canada Ltd" (the
  `docs/AGENT_DEMO.md` bucket-C example) now resolves 3 contracts across
  both Ottawa sources instead of 2, and still correctly declines cross-level
  exposure (still a single jurisdiction) -- the demo's behavior is
  unchanged, just backed by more data.
- **Real infrastructure fix, not scope-cosmetic.** `src/fetch.py`'s
  timestamped-directory + sha256-sidecar archival convention -- flagged in
  the previous verification pass as "effectively unused" -- was actually
  exercised for the first time on these two sources, including fixing a
  real `403`/silent-HTML-block-page failure mode against two different CDNs
  (see the ADR). The four original sources' raw files remain un-migrated to
  this convention; not touched here per that same ADR's original reasoning
  (re-fetching live feeds would change already-validated archived content).
- **Uncertainty, flagged not fixed.** `coverage.date_range_start` for
  `ottawa_contracts_awarded` reads 2023-06-30 (a report *period-end* date,
  since `extract_documents.py` stores period-end as every record's `date`),
  not the true 2023-01-01 start implied by that PDF's own text. This
  predates this session's changes, but it now visually reads as a Jan-Jun
  2023 coverage gap between the two Ottawa sources when the real coverage is
  contiguous. Worth fixing in `build_entity_store`'s date-range computation
  (or in how `_release()` stores `date`) before this table is relied on for
  a precise date-range claim; not fixed here since it's pre-existing and
  outside what was asked.
- **Not done.** The LLM-adapter ask ("add LLM calls to adaptors, if possible
  and useful") is wired up as a decision, not as code: no `ANTHROPIC_API_KEY`
  or `anthropic` dependency exists in this environment, so a real,
  token/cost-logged model call was not fabricated. `canadabuys_contract_history`'s
  mapping was hand-written and verified against the real CSV header instead
  (`sources/canadabuys_contract_history/mapping.yaml`), the same "phase-6-manual"
  path every other reviewed mapping in this repo already uses. Whether to
  supply a key so a real call can be made and logged is Adam's call.
- **Human verification before relying on this for the resume writeup.**
  (1) Spot-check `ottawa_historical_contracts` against a couple of the
  source Excel rows directly, the way the original Ottawa PDF extraction was
  spot-checked -- this session did not repeat that check. (2) Confirm the
  Ontario-second-source and 2016-2019/H2-2020 search conclusions with your
  own domain knowledge; a general web search is not exhaustive. (3) Decide
  whether to supply an LLM API key to close the real-model-call gap, or to
  revise the resume line to not claim it.

## Data browser Artifact (2026-09-11)

- Built `scripts/export_snapshot.py` (deterministic, read-only, reuses
  `src/agent_tools.py` — no logic duplicated) and `demo/register_template.html`
  (self-contained static page, one embedded variable font, vanilla JS,
  client-side gunzip of the exported snapshot). Published as a Claude
  Artifact: a searchable/filterable ledger of all 14,523 records plus a
  dedicated "vendors resolved across jurisdictions" section surfacing all 233
  cross-jurisdiction matches (headlined by Stantec Consulting Ltd, resolved
  across all three levels with 129 linked contracts) and the same coverage
  caveats the MCP server returns.
- Decision and rejected alternative in `docs/DECISIONS.md`: static snapshot,
  not a live backend — matches the "no server, no cloud infra" stack rule.
- Uncertainty: this is a point-in-time snapshot that goes stale the moment
  the warehouse changes; regeneration is a manual, documented step
  (`uv run python scripts/export_snapshot.py`, republish), not automatic.

## Phase 6 — MCP server and agent tools (2026-09-11)

- Acceptance test used (adapted from RUNBOOK, since the agent-eval half needs
  Phase 2 gold questions that don't exist): all five typed tools implemented,
  unit-tested against a synthetic warehouse (12 tests covering both happy
  paths and every refusal branch), smoke-tested end-to-end via an in-memory
  FastMCP client against the real `data/warehouse.duckdb`, and verified live
  over the exact stdio command Claude Desktop will invoke.
- Result: passed. `resolve_vendor("Bell Canada")` returns ranked candidates
  across sources with genuine confidence scores (including an honest, known
  false-positive artifact — see below). `entity_profile` on the resolved
  "BELL CANADA" entity returns 28 contracts across federal and Ottawa.
  `cross_level_exposure` on that entity returns a real per-jurisdiction
  breakdown (`declined: false`) and correctly excludes 4 CanadaBuys records
  that happen to be $0 from the dollar total rather than summing them in.
  The same tool on "Kleenoil Filtration Canada Ltd" (Ottawa-only) correctly
  returns `declined: true` with a stated reason instead of fabricating a
  cross-level number — verified against live data, not a fixture.
- Decisions: refusal logic is entirely rule-based (jurisdiction count,
  entity-link confidence floor reusing `resolve.UPPER_THRESHOLD`, buyer
  sample-size floor), not LLM-judged; Claude Desktop is the agent UI, not a
  custom chat frontend — both are ADR entries in `docs/DECISIONS.md`.
- Bug found and fixed while smoke-testing against real data (not a fixture):
  the zero-amount exclusion caveat originally said "this source publishes no
  per-transaction award value" for *any* source with an all-zero result set.
  That's true for Ontario VOR by design but was flatly wrong for the 4
  CanadaBuys "Bell Canada" records that happen to be $0 (real messy source
  data, confirmed by direct inspection) — CanadaBuys does publish amounts.
  Reworded to not claim a source-level limitation from a result-level
  observation.
- Uncertainty: `resolve_vendor` will surface real matching noise from the
  known `token_set_ratio` superset-match issue (`FAILURES.md` #17) — e.g. a
  bare "Bell" scores as a 1.0 "exact" match against "Bell Canada". Left
  visible rather than filtered, since hiding it would misrepresent the
  resolution layer's actual, disclosed precision.
- Not done, and not claimed: a measured agent eval (tool-selection accuracy,
  bucket-B caveat rate, bucket-C refusal rate) against gold questions —
  `evals/gold/agent/questions.yaml` is still empty. `docs/AGENT_DEMO.md`'s
  two scripted prompts are a qualitative existence proof for success
  criterion 5, not a metric.
- Human verification before the next phase: connect Claude Desktop using
  `docs/AGENT_DEMO.md` and confirm the two demo prompts read the way they're
  expected to in an actual chat, not just via the test client.

## Verification and reproducibility pass (2026-09-11)

Not a new phase. Picked up the existing build to verify it reproduces, close
the Ottawa licensing question, rebuild the entity/coverage layer, run the
RUNBOOK "between phases" audit, and add a pytest suite. Full detail in the
written summary to Adam; this entry is the durable record.

**Reproducibility.** Added `scripts/rebuild.py`: reads only archived raw
payloads under `data/raw/` (no network), applies the reviewed mappings,
validates, loads all four in-scope sources, then rebuilds
`entity`/`entity_link`/`coverage`. Deleted `data/warehouse.duckdb` and ran it
three times; the `releases` table is byte-identical run over run once the
legitimately-varying `_provenance.fetched_at` timestamp is excluded from the
comparison. This is success criterion 4's warehouse half; `cli eval` (the
metrics half) still does not exist.

**Warehouse contents.** `releases`: federal_contracts (5,000),
canadabuys_award_notices (5,000), ontario_vor (1,822),
ottawa_contracts_awarded (2,701) — 14,523 rows, all four jurisdictions
represented, full provenance block on every row. `entity`: 6,392. `entity_link`:
14,523. `coverage`: one row per ingested source with `value_threshold`,
populated `date_range_start`/`date_range_end` (previously always NULL), and
`known_gaps` populated from real documented gaps (previously just echoed the
generic `notes` field).

**Ottawa licence — resolved, not deferred.** The Phase 4 blocker was never
actually closed: PDFs were downloaded and extracted in a later session
without the licence question being re-answered. Verified via the City's own
ArcGIS Hub catalogue (`ottawa.maps.arcgis.com/sharing/rest/search`) that the
"Contracts awarded / Delegation of Authority" report series is separately
catalogued on `open.ottawa.ca` as public items licensed under the City of
Ottawa Open Data Licence v2.0, which permits redistribution and reuse with
attribution. 7 of 8 locally archived filenames matched a catalogued item title
exactly. Loaded the 2,701 already-extracted Ottawa records into the
warehouse on that basis. Full verification trail and caveats (series-level
confirmation, not byte-identity; the catalogue's items are structured Feature
Services, a materially better ingestion path than PDF parsing) are in
`sources/ottawa_contracts_awarded/source.yaml` and `docs/BLOCKED.md`.

**Phase 0 gap closed.** The archived CanadaBuys OCDS pilot zip that Phase 0's
"passed, 250 releases" result depended on was never archived under
`data/raw/`, breaking rule 3 and making the original result unreproducible.
Re-fetched it, archived it properly (`data/raw/canadabuys_ocds_pilot/`, with
a sha256 sidecar), and re-ran the acceptance test: still 250 releases, still
passes.

**Re-run acceptance tests.** Phase 0 (250 pilot releases validate — pass,
see above). Phase 1 (all four sources ingest, validate, load; one query
returns all four with full provenance — pass, now four sources instead of
three since Ottawa loaded). Phase 5 provisional resolution eval against
`evals/provisional/resolution/pairs.csv` — re-ran, output byte-identical to
the committed `evals/results/PROVISIONAL_resolution_metrics.log`, still
labelled PROVISIONAL. None of these needed loosening to pass.

**Audit findings (RUNBOOK "between phases").** No fabricated metrics found;
every number outside `evals/results/PROVISIONAL_*` traces to spec text
explicitly marked as a placeholder (Part 13). No source substituted without a
flag — the Ontario VOR swap was already correctly disclosed with an ADR. Real
findings, all now documented:
1. **`mapping.yaml` is not actually applied.** `apply_mapping.py` branches on
   hardcoded `if source_id == "..."` per source and never reads
   `source_field`/`transform` out of the YAML; `extract_documents.py` doesn't
   consult Ottawa's mapping.yaml either. Confirmed by cross-check: 7 of 17
   distinct `transform:` values used across the four mapping.yaml files
   aren't in `transform_registry.TRANSFORMS` at all — they were never
   exercised. `mapping.yaml` is currently reviewable documentation, not
   load-bearing config. See the ADR in `docs/DECISIONS.md`; this is a human
   call, not something fixed here.
2. **Federal sources are a truncated, non-random slice.** `federal_contracts`
   and `canadabuys_award_notices` raw files have ~1.39M and ~786K data rows;
   only the first 5,000 in file order are loaded (spec's cap, but the scale
   and non-randomness of the truncation was previously undocumented). Now in
   each source's `known_gaps`.
3. **`coverage.date_range_start/end` were always NULL** and `known_gaps` just
   repeated the generic `notes` field — both fixed (see above); this table
   exists specifically to make agent refusals honest, so half-populating it
   defeated the point.
4. **`required_source_field` was dead config.** `apply_mapping.py` supports
   filtering footer/note rows via `required_source_field`, and Phase 1's own
   decision log claims Ontario VOR footer rows are excluded this way — but no
   `mapping.yaml` ever set it, so the current Ontario export (which happens
   to have zero such rows right now) would silently ingest a footer row as a
   fake vendor if one ever appeared, or crash `validate_releases` since a
   blank `ocid`/`id` fails the schema's `minLength: 1`. Fixed:
   `sources/ontario_vor/mapping.yaml` now sets it. Verified with a test that
   the current 1,822-row load is unaffected.
5. **`pytest.ini_options.pythonpath = ["src"]` was broken** for any module
   using package-relative imports (`apply_mapping.py`, `resolve.py` via
   `transform_registry`, `generate_mapping.py`, `extract_documents.py`) —
   never caught because no tests existed. Fixed to `["."]`.
6. **A resolution false positive**, found writing tests, not chased down
   separately: `classify_pair("Acme Consulting Inc.", "Acme Consulting Group
   Inc.")` scores 100.0 and auto-accepts, but the provisional gold-shaped
   pairs file labels this exact pair `no-match`. It's `token_set_ratio`
   treating a strict token superset as a full match; it's one of the three
   false positives already counted in the federal↔on precision figure.
   Catalogued as `docs/FAILURES.md` #17. Not fixed — the scoring function is
   Phase 5's known, disclosed weak point, and this is a concrete instance of
   it, not a new bug.
7. **`src/fetch.py` (timestamped-directory + sha256-sidecar convention) is
   effectively unused.** Every raw file that predates this pass sits in a
   `phase1/` or `active/` folder with no hash sidecar, meaning it wasn't
   fetched through the one script that enforces the immutable-archive
   convention. Nothing has been modified post-fetch (rule 3 intent is
   intact), but the fetch provenance chain (exact fetch time, hash) doesn't
   exist for the original four sources the way it now does for the
   Phase-0 pilot re-fetch. Not fixed — re-fetching the original three CSVs
   now would change their content (they're live feeds) and there's no
   reason to disturb already-validated archives.
8. **No `README.md`** at the repo root, though spec Part 6's architecture
   lists it first. Not written here — it's a human-voice deliverable per
   the RUNBOOK's writeup split, not something to draft speculatively.
9. Phase 4's RUNBOOK explicitly assigns "spot-check ten extracted records
   against the source PDFs yourself" to the human reviewer. The commit that
   resumed Ottawa extraction had the agent perform that check itself
   instead. Flagging it, not redoing it — a second, independent spot-check by
   Adam is still worth doing before trusting the 2,701 Ottawa records.

**Tests added.** `tests/` (56 tests, all deterministic, no network, no model):
`test_validate.py`, `test_apply_mapping.py` (against the real committed
`mapping.yaml` files with synthetic fixture CSVs), `test_resolve.py`
(normalization, blocking, scoring, classification, the evaluate_pairs
report shape), `test_transform_registry.py`, `test_extract_documents.py`
(regex/parsing units plus one integration test against the real archived
Ottawa PDFs, skipped if they're absent). `uv run pytest` — 56 passed.
`uv run ruff check .` — clean throughout.

**Still true, unchanged by this pass:** Phase 2 gold sets do not exist and
were not touched. No real LLM call has ever been made; `evals/results/llm_calls.jsonl`
does not exist. `src/generate_mapping.py`'s offline scaffold and the
resolution adjudication band remain untested against real model behaviour.
Phases 6 and 7 (MCP server, agent, gating sweep, writeup) were not started.
Success criterion 1 ("seven or more sources") is not met — four sources are
actually ingested; `canadabuys_ocds_pilot` is schema-validation-only by
design, and Ontario ministry notices / Open Ottawa / CanadaBuys contract
history were never built as real adapters.

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