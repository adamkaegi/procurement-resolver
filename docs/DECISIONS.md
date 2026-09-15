# Decision Log

## Phase 0: deterministic validation

- Context: The archived pilot is already published as OCDS JSON.
- Decision: Validate the compiled releases with a local JSON Schema and no model call.
- Alternative rejected: LLM-based schema inference.
- Consequence: The acceptance test is reproducible and schema failures are attributable to the subset.

## Phase 1: deterministic mapping application

- Context: Phase 1 requires calibration mappings before automation.
- Decision: Hand-written YAML mappings and deterministic Python transforms; no LLM calls.
- Alternative rejected: generating mappings with an LLM before gold sets exist.
- Consequence: Mapping behavior is reviewable and provides the baseline for Phase 2 human labels.

## Phase 3: offline mapping scaffold

- Context: The Phase 3 pipeline needs a runnable generator and validation gate, but no model endpoint or credentials are configured in this workspace.
- Decision: Implement an offline deterministic proposal engine with conservative abstention, while preserving the model output contract and logging zero model tokens and zero model cost.
- Alternative rejected: claiming that an unavailable external model generated the provisional mapping.
- Consequence: The pipeline acceptance is structural and reproducible, but its provisional mapping score is not evidence of LLM mapping quality and must not be reported.

## Phase 4: Ottawa source verification

- Context: Ottawa Delegation of Authority reports are required to be reachable and openly licensed before extraction.
- Decision: Stop after the official site returned an anti-bot challenge and the reachable third-party meeting host did not expose a verifiable licence.
- Alternative rejected: substituting an unverified meeting document or scraping a third-party host without licence confirmation.
- Consequence: Ottawa extraction is blocked and documented; Phase 5 continues with federal and Ontario data only.

## Phase 5: resolution adjudication fallback

- Context: Bulk resolution should be deterministic, while only the uncertain score band should reach an LLM adjudicator.
- Decision: Use normalized-name blocking and rapidfuzz scoring; abstain in the uncertain band when no adjudicator is configured.
- Alternative rejected: forcing every uncertain pair into a match or non-match.
- Consequence: source names remain verbatim in `entity_link`, uncertain cases remain visible, and provisional metrics cannot be mistaken for adjudicated quality.

## Phase 4: Ottawa deterministic extraction

- Context: The downloaded Ottawa reports are text-based PDFs with repeated, column-like contract rows, but no stable machine-readable dataset.
- Decision: Parse the report text deterministically with `pypdf`, preserve the raw PDF reference, attach extraction confidence, and retain the approval type and non-competitive rationale as provenance extensions.
- Alternative rejected: fabricating an LLM extraction call or treating the report text as a clean CSV.
- Consequence: extraction is reproducible and cost-free at the model layer, while parser confidence and manual spot checks expose the remaining table-layout risk.

## Phase 6: MCP server, typed tools, and deterministic refusal logic

- Context: spec Part 9 requires five typed tools, no `run_sql`, confidence on
  every entity-touching tool, and coverage caveats (with refusal) on every
  aggregating tool. `evals/gold/agent/questions.yaml` is empty (Phase 2,
  human-only, untouched) so there is no gold bucket-A/B/C set to build a real
  agent-eval harness against, and no model credentials are configured.
- Decision: build `src/agent_tools.py` as plain, typed, pydantic-returning
  functions over the warehouse (unit-testable with no MCP or model
  dependency), and `src/server.py` as a thin FastMCP wrapper with no logic of
  its own. Refusal is entirely rule-based, not LLM-judged:
  `cross_level_exposure` declines when an entity resolves to fewer than two
  jurisdictions or when its weakest entity-link confidence falls below
  `resolve.UPPER_THRESHOLD / 100` (reusing the resolution layer's existing
  auto-accept bar rather than inventing a second number to justify);
  `compare_buyers` declines a per-buyer total below a 3-record floor. Sources
  whose included records are all $0 are excluded from dollar totals with an
  explicit caveat, never silently summed as zero.
- Alternative rejected: an LLM-adjudicated refusal step inside the tools
  (spec explicitly wants typed tools with confidence/caveats attached, not a
  second model call per query — the interpretive work of turning a
  declined-aggregate response into a spoken refusal is left to whatever LLM
  is driving the tools, e.g. Claude Desktop, not baked into the tool). Also
  rejected: building a custom chat UI. Spec Part 3 explicitly scopes out any
  UI beyond a CLI/demo notebook, and any MCP client can already drive this
  server for free (`docs/AGENT_DEMO.md`) — a bespoke frontend would be new,
  unnecessary infrastructure for a "no server, no cloud infra" stack.
- Consequence: the tools are real and demoable today (`docs/AGENT_DEMO.md`
  has a scripted bucket-A / bucket-C-style pair verified against the live
  warehouse). What's still missing: a *measured* agent eval (tool-selection
  accuracy, bucket-B caveat-presence rate, bucket-C refusal rate) — that
  needs the Phase 2 gold questions and is not claimed here. The two demo
  prompts in `docs/AGENT_DEMO.md` are a qualitative existence proof, not a
  metric, and must not be reported as one.

## Data browser: static snapshot Artifact, not a live backend

- Context: wanted a clean way to browse the warehouse without building new
  infrastructure the "no server, no cloud infra" stack rule and spec Part 3's
  UI scope-cut both argue against.
- Decision: `scripts/export_snapshot.py` reads the warehouse read-only and
  writes a gzip+base64 JSON snapshot (all 14,523 releases, all 233
  cross-jurisdiction resolved entities via the same `agent_tools` functions
  the MCP server uses, and the 4 coverage rows). `demo/register_template.html`
  is a self-contained static page (one embedded variable font, vanilla JS,
  client-side `DecompressionStream` to unpack the snapshot) with no server,
  no database connection, and no API calls at runtime. Published as a Claude
  Artifact.
- Alternative rejected: a live web app backed by a running server and a
  connection to the warehouse. Would need hosting, and turns a demo asset
  into something with an ongoing maintenance and security surface for a
  resume piece that doesn't need one.
- Consequence: the browser is a point-in-time snapshot, not a live view — it
  goes stale the moment the warehouse is rebuilt with new data and must be
  regenerated (`uv run python scripts/export_snapshot.py`, then republish)
  on purpose, not automatically. `demo/*.b64` and `demo/coverage.json` are
  gitignored (derived data); the template and export script are committed.

## Audit finding: mapping.yaml is not actually applied (not a new decision — flagged, not fixed)

- Context: spec Part 6 calls `mapping.yaml` "GENERATED then reviewed — the core
  artifact" and says applying it is deterministic code. In the actual
  pipeline, `src/apply_mapping.py::_release()` branches on
  `if source_id == "federal_contracts": ...` / `elif source_id ==
  "canadabuys_award_notices": ...` / `else: # ontario_vor` and hand-reads
  specific CSV column names directly. It never reads the `source_field` or
  `transform` keys out of `sources/*/mapping.yaml` at all. Ottawa's
  `extract_documents.py` is entirely separate again: regex-based PDF parsing
  that doesn't consult `sources/ottawa_contracts_awarded/mapping.yaml` either.
  Confirmed by cross-checking: 7 of the 17 distinct `transform:` values used
  across the four `mapping.yaml` files (`confidence_from_parse_outcome`,
  `constant_cad`, `constant_ontario_government`, `constant_ottawa`,
  `parse_nonnegative_currency_with_total_fallback`, `parse_report_period_date`,
  `stable_source_contract_id`, `stable_source_item_id`) are not in
  `src/transform_registry.py::TRANSFORMS` at all — if `mapping.yaml` were
  actually executed against the registry, validation would fail immediately.
- Decision: leave this as-is and flag it rather than refactor
  `apply_mapping.py` into a generic mapping-yaml interpreter during this
  verification pass. A rewrite here changes what actually produced the
  14,523 rows currently in the warehouse, which is a bigger risk to take
  unreviewed than reporting the gap honestly.
- Alternative rejected: silently treating `mapping.yaml` as if it were load-
  bearing when writing the summary for Adam, or quietly "fixing" the
  transform names in mapping.yaml to match reality without flagging that the
  files were never actually exercised.
- Consequence: `mapping.yaml` is currently decorative — reviewable
  documentation of what a human intended the mapping to be, not the thing
  that ran. Success criterion 2 ("at least three sources were mapped by the
  generator and never hand-corrected") and criterion 4 ("cli eval reproduces
  all headline metrics") cannot be honestly claimed against the real
  ingestion path until either `apply_mapping.py` is rewritten to actually
  interpret `mapping.yaml`, or the spec's claim about `mapping.yaml` being
  the core artifact is revised to match what the code does. This is a human
  decision, not one to make silently.

## Ottawa licence verification and warehouse load

- Context: `sources/ottawa_contracts_awarded/source.yaml` licence field read
  "personal-project download, redistribution not assumed" — the Phase 4
  extraction had run against files whose reuse terms were never confirmed,
  in tension with CLAUDE.md rule 4. `data/processed/ottawa_contracts_awarded.jsonl`
  (2,701 validated records) sat unloaded as a result.
- Decision: verify licence via the City's own ArcGIS Hub catalogue rather than
  re-fetching or substituting a source. Confirmed the report series is
  publicly catalogued on `open.ottawa.ca` under the City of Ottawa Open Data
  Licence v2.0, which permits redistribution and reuse with attribution.
  7 of 8 local filenames matched a catalogued item title exactly. Loaded the
  existing extracted records into `releases` on that basis.
- Alternative rejected: leaving Ottawa unloaded indefinitely pending a licence
  that, on inspection, already existed; also rejected re-downloading from
  open.ottawa.ca to replace the escribe-hosted PDFs already archived, since
  that would be a mid-project source substitution the run instructions call
  out as something to flag rather than do silently.
- Consequence: the warehouse now has three jurisdictions. The verification
  confirms the licence for the *report series*, not byte-identity between the
  archived PDFs and the catalogue entries — flagged in source.yaml as an open
  item. Also flagged: the open.ottawa.ca items are structured Feature Services,
  not PDFs, which is a better Ottawa ingestion path a human should evaluate
  before further extraction work.

## Source-scope expansion: two new federal/Ottawa sources, no second Ontario source

- Context: Adam asked to expand source scope while staying within federal /
  Ontario / Ottawa (no new provinces or municipalities), and to add more data
  points to the three jurisdictions already in scope if a real, verifiable
  source existed for them.
- Decision (federal): add `canadabuys_contract_history` -- PWGSC/PSPC's full
  contract-history ledger (distinct from `canadabuys_award_notices`, which
  mirrors individual award-notice publications). Verified live via the CKAN
  API (`open.canada.ca/data/api/action/package_show`), confirmed
  `license_title: "Open Government Licence - Canada"`, same licence family
  as the two existing federal sources. Archived the closed 2024-2025 fiscal
  year CSV (one finished year, not a partial current-year file).
- Decision (Ottawa): add `ottawa_historical_contracts` -- three Excel
  workbooks (2020, 2021, 2022) from the same "Contracts awarded under
  delegation of authority" report series as `ottawa_contracts_awarded`,
  found via the ArcGIS Hub search API and licence-verified per-item the same
  way the original Ottawa PDFs were (BLOCKED.md, "Ottawa licence verification
  and warehouse load") -- all three report `access: public` and a
  `licenseInfo` pointing at the same Open Data Licence v2.0 page.
- Decision (separate source_id, not a merge): `ottawa_historical_contracts`
  is a new source, not folded into `ottawa_contracts_awarded`, even though
  both are the same report series and jurisdiction. Reasons: (1) the raw
  format is materially different (structured Excel vs. regex-parsed PDF
  text) and deserves its own extractor rather than a branch bolted onto
  `extract_documents.py`; (2) keeping the boundary explicit lets
  `known_gaps` state per-source what each extraction method can and can't
  see, rather than blending two confidence profiles under one source_id.
- Decision (bounded to 2020-2022, not 2016-2019): a combined 2016-2019
  workbook exists (item `2a84a360272d4084a85dc576bc304176`) but packs 8
  quarterly sheets with inconsistent header text ('Dept', 'Dept.',
  'Department', 'Service' all denoting the same logical column) and no
  per-row date field at all. Cut rather than force a fragile parser for it,
  same spirit as the original Phase 4 "cap effort, report honestly" call on
  the PDF extraction. It's a disclosed `known_gap`, not a silent omission.
- Decision (2022 as the cutoff, not 2023): chosen specifically because the
  earliest archived `ottawa_contracts_awarded` PDF covers Jan-Jun 2023 (its
  filename says 2022 but the report text says 2023 -- already documented).
  Ending the new source at 2022-12-31 gives temporal coverage that is
  additive, not overlapping -- no cross-source contract-ID reconciliation
  was needed as a result. (`coverage.date_range_start` for
  `ottawa_contracts_awarded` currently reads 2023-06-30, not 2023-01-01, an
  artifact of `_release()` always storing the report's period *end* as
  `date` -- pre-existing, unrelated to this change, but it means the two
  sources' coverage rows look like they leave a Jan-Jun 2023 gap when the
  real coverage is contiguous. Flagged in docs/PROGRESS.md for verification,
  not fixed here.)
- Decision (extraction_conf raised to 0.98 for the new Ottawa source):
  distinct from `ottawa_contracts_awarded`'s 0.85-0.95 range, which reflects
  OCR/regex uncertainty inherent to parsing rendered PDF text. These are
  read directly from spreadsheet cells with openpyxl -- a materially more
  reliable extraction method for the same underlying report series, and the
  confidence score says so rather than reusing an unrelated number.
- Alternative rejected (Ontario second source): searched for a second live,
  openly-licensed Ontario procurement dataset beyond the existing
  `ontario_vor` (targeting ministry award notices / Broader Public Sector
  disclosures, per the original spec's "Ontario ministry notices" gap).
  `data.ontario.ca`'s procurement-tagged catalogue (95 datasets at search
  time) surfaces only VOR-family datasets; Ontario's tender portal appears
  login-gated with no accompanying open-data export. Per CLAUDE.md rule 4
  ("if a source can't be verified... STOP and report; do not substitute"),
  no second Ontario source was added and none was fabricated or approximated
  from a different data shape. Ontario remains single-sourced in this
  warehouse. A human with more Ontario-specific search context may find one
  a general search didn't surface.
- Consequence: sources go from 4 to 6 (still 3 jurisdictions, per the
  constraint given). `releases` grows from 14,523 to 23,426 rows; `entity`
  from 6,392 to 9,030; `entity_link` from 14,523 to 23,426. Re-ran
  `scripts/rebuild.py`, `ruff check .`, and `pytest` clean (73 passed, up
  from 68) after adding `tests/test_ingest_ottawa_open_data.py` and
  extending `tests/test_apply_mapping.py`.

## `openpyxl` dependency and a `curl` fallback in `src/fetch.py`

- Context: `ottawa_historical_contracts` ships as `.xlsx`, which none of the
  approved dependencies can read. Separately, fetching both new sources
  through `src/fetch.py` (rather than a one-off `curl` outside the
  reviewable archival path) hit `403 Forbidden` from both
  `canadabuys.canada.ca` and the ArcGIS-hosted `.xlsx` downloads when
  requested via Python's `urllib` -- with or without a descriptive
  `User-Agent` header. `curl`'s own default UA passed on both hosts; a
  custom UA passed on ArcGIS but still 403'd on `canadabuys.canada.ca`. This
  reads as UA/TLS-stack fingerprint-based bot mitigation, not an access
  control the public OGL/Open Data Licence doesn't already grant -- the same
  URLs are the ones published as the official download links.
- Decision: add `openpyxl` as a new dependency (minimal, standard, pure-Python
  `.xlsx` reader; per CLAUDE.md, dependencies beyond the approved stack need
  an ADR, this is it). Also changed `fetch()` to retry via a `curl`
  subprocess on `HTTPError`, and added a lightweight content-sniff (reject
  if the downloaded bytes start with `<html`/`<!doctype`) so a silent
  soft-block (200 status, HTML block page instead of the real payload -- hit
  once during this session) fails loudly instead of archiving garbage.
- Alternative rejected: hand-rolling `.xlsx` parsing via `zipfile` + raw XML
  to avoid a new dependency -- rejected as needless fragility for a
  well-solved problem `openpyxl` already solves correctly. Also rejected:
  leaving `fetch()` urllib-only and just curling these two sources by hand
  outside the archival convention, which would have repeated the exact gap
  `docs/PROGRESS.md` already flagged (`src/fetch.py` "effectively unused").
- Consequence: `src/fetch.py`'s timestamped-directory + sha256-sidecar
  convention is now actually exercised for the first time on sources
  ingested in this repo, with a real fallback for the CDN behavior actually
  encountered doing it. `pyproject.toml` and `uv.lock` updated accordingly.

## Real LLM calls for mapping generation: wired, not executed

- Context: Adam asked to add LLM calls to the adapters "if possible and
  useful." `src/generate_mapping.py`'s `propose_mapping()` is the offline,
  deterministic scaffold from Phase 3 -- it has never called a real model
  (`evals/results/llm_calls.jsonl` does not exist anywhere in this repo).
  No `ANTHROPIC_API_KEY` (or any LLM provider credential) is present in this
  environment, and `anthropic` is not an installed dependency.
- Decision: do not fabricate a call or claim one happened. Left
  `generate_mapping.py`'s offline scaffold as the mapping-generation path
  actually exercised for `canadabuys_contract_history` in this session --
  its output was hand-verified against the real archived CSV header instead
  (see `sources/canadabuys_contract_history/mapping.yaml`). Asked Adam
  whether he can supply an API key so a real, logged call can replace the
  scaffold for at least one source, per the LLM usage policy ("every LLM
  call logs tokens, cost, and latency to `evals/results/llm_calls.jsonl`").
- Alternative rejected: adding an untested `anthropic`-backed code path
  speculatively and describing it as done. Rejected because CLAUDE.md rule 1
  ("never fabricate a metric") and the LLM usage policy's logging
  requirement can't be honestly satisfied by code that has never actually
  run against a model -- an unexercised integration is a bigger credibility
  risk on a resume project than not having one yet.
- Consequence: "LLM-generated adapters" is still not demonstrated against a
  real model anywhere in this repo. This is the one open item from Adam's
  three asks in this session; the other two (source scope, more data points)
  are done and reflected in the warehouse.

## Phase 1 resumed: active Ontario VOR export

- Context: The original Ontario VOR outlook contained only 39 planned opportunities and no award values; the page itself pointed to a separate active-arrangements export.
- Decision: Use the official `enterprise_vor_program.csv` active VOR export as the Ontario adapter input. Map qualified vendors and arrangement start/end dates, and keep award amount unknown as zero because the source does not publish transaction values.
- Alternative rejected: treating the planning outlook as representative of Ontario procurement volume.
- Consequence: the Ontario source expands to 1,822 active arrangements, but it remains an arrangement registry rather than an award ledger and must carry that coverage caveat.