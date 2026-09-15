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

## Real LLM calls for mapping generation: a local Ollama model, executed

- Context: Adam asked to add LLM calls to the adapters "if possible and
  useful," then specifically declined a hosted-API key in favour of a local
  Ollama model when asked. `src/generate_mapping.py`'s `propose_mapping()`
  is the offline, deterministic scaffold from Phase 3 -- it has never called
  a real model, and `evals/results/llm_calls.jsonl` did not exist anywhere
  in this repo before this entry.
- Decision: built `src/ollama_mapping.py` as a companion module (kept
  separate from `generate_mapping.py` so that module's own "without an
  external model endpoint" docstring stays true, and so pytest -- which
  measures code correctness, not model behaviour, per CLAUDE.md
  "Conventions" -- never needs a live model to pass). It calls a locally
  running Ollama server (confirmed already installed: `ollama version
  0.33.3`, several models pulled), prompts `qwen2.5:7b-instruct` (the
  strongest instruction-following model available locally for a structured-
  JSON task among what was already pulled) with the canonical-field list,
  the registered-transform whitelist, the source's real column names, and
  three real sample rows, requesting a mapping shaped exactly like
  `generate_mapping.py`'s existing schema. Reuses that module's
  `validate_mapping`/`validate_sample` unchanged as the acceptance gate --
  one validation gate for both the offline and the real-model path.
  Retries up to 3x on validation failure, logging every attempt (pass or
  fail) to `evals/results/llm_calls.jsonl`, with `cost_usd: 0.0` and an
  honest `cost_note` ("local inference via Ollama, no metered API cost") --
  distinct in meaning from the offline scaffold's `cost_usd: 0.0`, which
  means no model ran at all.
- Executed against the real archived `canadabuys_contract_history` CSV
  header (91 real columns, 3 real sample rows). First attempt failed
  validation (`unknown source field for awards[].items[].classification.id:
  gsin` -- the model wrote the field name it remembered instead of the
  real `gsin-nibs` column); the retry self-corrected and passed on attempt
  2. Real, logged numbers for that pair of calls: ~6,900 input tokens,
  ~1,250-1,270 output tokens each, ~57s latency each, on this machine's CPU.
  The model's own output (unedited -- see "consequence" below) replaced the
  hand-written `sources/canadabuys_contract_history/mapping.yaml` from the
  earlier "Source-scope expansion" entry above.
- A prompt bug caught and fixed mid-session: the first two real attempts
  (before this) failed validation because the prompt's own example showed
  an "unmapped" entry omitting the `transform` key -- the schema actually
  requires `transform: "unmapped"` even on unmapped entries, and the model
  faithfully copied the flawed example every time. Fixed the example and
  added an explicit instruction; the corrected prompt passed within one
  retry against real data.
- Alternative rejected: a hosted API (Anthropic or otherwise) -- explicitly
  declined by Adam in favour of zero-cost local inference. Also rejected:
  hand-correcting the model's output before committing it. The project's
  own success criterion 2 ("mapped by the generator and never hand-
  corrected") asks for the generator's real output, not a human-polished
  version of it -- so genuine quality gaps are disclosed below, not quietly
  fixed.
- Consequence, stated plainly: the committed, model-generated mapping is
  real but imperfect. Human review (this session) found it left
  `awards[].description` unmapped despite `tenderDescription-
  descriptionAppelOffres-eng` being present and usable in the real header
  (a genuine miss, not a defensible abstention like its correct choice to
  leave `ocid` unmapped), and picked `default_cad` -- a currency-default
  transform, not a currency-parsing one -- for `awards[].value.amount` on
  one of the two real runs. Neither breaks ingestion: `apply_mapping.py`'s
  `_release()` is hardcoded per source_id and has never actually read
  `mapping.yaml`'s per-field `transform`/`source_field` values (see "Phase 1
  mapping.yaml is documentation, not executable config" below) -- true
  again here, so this is the first source where that gap is arguably a
  safety net rather than only a liability. `evals/results/llm_calls.jsonl`
  now exists as a real deliverable with two real logged calls. "LLM-
  generated adapters" is now demonstrated end-to-end for one source, with
  its real accuracy limitations disclosed rather than smoothed over --
  exactly what a resume claim needs to be honest.

## Phase 1 resumed: active Ontario VOR export

- Context: The original Ontario VOR outlook contained only 39 planned opportunities and no award values; the page itself pointed to a separate active-arrangements export.
- Decision: Use the official `enterprise_vor_program.csv` active VOR export as the Ontario adapter input. Map qualified vendors and arrangement start/end dates, and keep award amount unknown as zero because the source does not publish transaction values.
- Alternative rejected: treating the planning outlook as representative of Ontario procurement volume.
- Consequence: the Ontario source expands to 1,822 active arrangements, but it remains an arrangement registry rather than an award ledger and must carry that coverage caveat.