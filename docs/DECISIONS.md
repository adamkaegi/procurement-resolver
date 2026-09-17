# Decision Log

Every deterministic-vs-LLM choice and every architectural trade-off in this
project, in the format context / decision / alternative rejected /
consequence, grouped by area rather than by when each was made. This is the
source material for the project writeup, and the place to look for *why*
the code is shaped the way it is.

## Schema and validation

### Validate against the archived OCDS pilot, not an invented fixture

- Context: the canonical schema (`schema/ocds_subset.json`) needed a real
  acceptance check before anything was built on top of it.
- Decision: validate against PSPC's own archived OCDS pilot release (250
  real records, already published in OCDS form) with a local JSON Schema
  validator and no model call.
- Alternative rejected: LLM-based schema inference from sample data.
- Consequence: schema failures are attributable to the subset definition,
  not to a fixture built to make the schema look correct.

## Mapping and ingestion

### Hand-written mappings before any generator

- Context: a mapping generator needs a correct mapping to compare itself
  against, and to distinguish "abstained" from "wrong."
- Decision: hand-write `mapping.yaml` and deterministic Python transforms
  for the first three sources; no LLM calls at this stage.
- Alternative rejected: generating mappings with an LLM before any
  hand-verified baseline exists.
- Consequence: mapping behavior for these sources is fully reviewable, and
  gives the mapping generator something real to be measured against.

### `mapping.yaml` is executed, not decorative

- Context: for most of this project's life, `apply_mapping.py` branched on
  `source_id` with hardcoded column reads, and `mapping.yaml` was reviewable
  documentation of intent rather than the thing that ran — a disclosed
  trade-off (the risk of rewriting what produced every warehouse row was
  judged worse than the config-vs-code gap). That gap was this repo's
  biggest plan-vs-code divergence.
- Decision: replace the per-source branches with a generic interpreter.
  Each `mapping.yaml` entry names its canonical field, its source column(s)
  — fallback order declared as `source_fields` lists in the config, not
  encoded in transform names — and a transform that is now a real function
  in `transform_registry.py` (`direct`/`first_present`, `parse_date`,
  `parse_currency`, `parse_nonnegative_currency_with_total_fallback`,
  `default_cad`, `constant`). Structural fields no source publishes
  (initiationType, tag, buyer.id, jurisdiction, award id/date mirroring,
  provenance) are supplied uniformly by the interpreter. The Ottawa
  document sources stay code-driven extractors by design — they parse
  documents, not columns.
- Alternative rejected: keeping the hardcoded dispatch permanently, or
  migrating without an equivalence check.
- Consequence: verified by rebuilding every CSV source through the
  interpreter and comparing against the previous warehouse — all four
  sources byte-identical except the provenance fields that legitimately
  changed (`field_origins` is now more complete, `mapping_version` for the
  reviewed mapping). A new CSV source now needs only a `mapping.yaml`, no
  Python branch — a mapping without a release identity (`ocid`/`id`) fails
  loudly. The validation gate got stronger for free: `validate_sample`
  applies a candidate mapping through this same interpreter, so a mapping
  that is structurally well-formed but produces invalid records now fails
  the gate (the previous gate validated a hardcoded assembly instead, and
  passed mappings the interpreter would have rejected).

### Generated, then reviewed

- Context: `sources/canadabuys_contract_history/mapping.yaml` was committed
  as unedited Ollama output (`qwen2.5:7b-instruct`, generation logged in
  `evals/results/llm_calls.jsonl`), under a "never hand-corrected" framing.
  Once mapping.yaml became executable, that framing collided with reality:
  executed literally, the model's mapping fails ingestion — it left
  schema-required `ocid` unmapped, mapped the amount to a single column
  with no negative-amendment fallback (amendment rows would fail the
  schema's `minimum: 0`), left a populated description column unmapped, and
  chose a sparsely-populated identifier column.
- Decision: adopt the pipeline the spec always drew — "generate mapping
  (once/source) → human review" — with the review allowed to correct.
  The unedited model output is archived beside the executable mapping
  (`mapping.ollama_unedited.yaml`) with each correction named in the
  reviewed file's header, and the generation's real tokens/latency/cost
  stay logged. The offline deterministic proposal scaffold (a hint table
  containing the actual sources' column names — a lookup of known answers
  that a close reader would rightly distrust) was deleted along with its
  provisional outputs; `generate_mapping.py` is now purely the validation
  gate, and `ollama_mapping.py` is the one generation path.
- Alternative rejected: executing the model's mapping untouched (drops or
  degrades real records to preserve a claim about process); keeping that
  one source hardcoded as an exception (keeps the gap the interpreter
  exists to close).
- Consequence: the "never hand-corrected" claim is retired — what's
  demonstrated instead is the honest loop: real model generation, a gate
  that now catches its real failure modes (the archived unedited mapping
  fails the strengthened gate with 8 errors; the reviewed one passes), and
  a reviewable diff between what the model proposed and what a human
  shipped. That diff is a better artifact about LLM-generated adapters
  than an untouched-but-broken mapping was.

## Ottawa: licence verification and extraction

### Licence verified via the City's own open-data catalogue before ingesting

- Context: the City of Ottawa's Delegation of Authority reports needed a
  confirmed open licence before ingestion (CLAUDE.md rule 3). The official
  city site returned an anti-bot challenge; the only reachable host serving
  the actual PDFs, `pub-ottawa.escribemeetings.com`, is a third-party
  meeting-document surface that shows no licence of its own.
- Decision: rather than substitute a different source or proceed
  unverified, checked the City's actual open-data catalogue
  (`ottawa.maps.arcgis.com/sharing/rest/search`) directly. The same
  "Contracts awarded under Delegation of Authority" report series is
  separately published there as public items, each with `licenseInfo`
  pointing at the City of Ottawa Open Data Licence v2.0 (permits
  redistribution and reuse with attribution). 7 of 8 locally archived PDF
  filenames matched a catalogued item title exactly; the 8th matched by
  naming-pattern similarity to the same series. The later
  `ottawa_historical_contracts` source (2020–2022 Excel workbooks) was
  licence-verified the same way, item by item, before being added at all.
- Alternative rejected: scraping or substituting an unverified third-party
  host; leaving the already-extracted records unloaded indefinitely once a
  real licence was confirmed to exist; re-downloading from the catalogue to
  replace the already-archived PDFs (a source substitution, not a licence
  fix).
- Consequence: this confirms the *report series* is openly licensed, not
  byte-identity between the archived PDFs and the catalogue entries — noted
  in `sources/ottawa_contracts_awarded/source.yaml`. Also noted there: the
  catalogue's items are structured Feature Services, not PDFs, and would
  likely beat PDF text-extraction on both cost and accuracy for future work.

### Ottawa PDF extraction: deterministic regex parsing, not a model call

- Context: the downloaded Ottawa reports are text-based PDFs with repeated,
  column-like contract rows, not a structured export.
- Decision: parse report text deterministically with `pypdf`, preserve the
  raw PDF reference, attach a numeric extraction confidence per record, and
  retain approval type and non-competitive rationale as provenance
  extensions.
- Alternative rejected: sending page text to an LLM for extraction, or
  treating the report text as a clean CSV.
- Consequence: extraction is reproducible and free at the model layer.
  Parser confidence (0.85–0.95, lower when department/approval-type/
  rationale aren't all found) and spot checks against source PDFs are the
  honesty mechanism in place of model-based extraction confidence.

### `ottawa_historical_contracts`: a separate source, not a merge

- Context: `ottawa_contracts_awarded` (PDFs, 2023 onward) and the City's
  2020–2022 Excel workbooks are the same underlying report series and
  jurisdiction.
- Decision: ingest the 2020–2022 workbooks as a distinct `source_id`
  (`src/ingest_ottawa_open_data.py`, `openpyxl`-based) rather than folding
  them into `ottawa_contracts_awarded`. Bounded to 2020–2022 (a combined
  2016–2019 workbook exists but has 8 inconsistently-headered sheets and no
  per-row date field — cut rather than force a fragile parser for it) and
  to 2022-12-31 specifically, so the two sources' date coverage is additive
  with zero overlap against the PDFs' 2023-01-01 start.
- Alternative rejected: one combined source spanning both formats, which
  would blend two different extraction-confidence profiles (structured
  spreadsheet cells vs. OCR/regex-parsed PDF text) under one `source_id` and
  obscure which method backs any given record. Also rejected: forcing a
  parser onto the inconsistent 2016–2019 workbook.
- Consequence: `ottawa_historical_contracts` records carry a higher
  `extraction_conf` (0.98) than `ottawa_contracts_awarded`'s PDF-parsed
  records (0.85–0.95), reflecting the more reliable extraction method
  honestly rather than reusing an unrelated number. 2020–2022 pre-dates
  this warehouse's federal/Ontario coverage for some vendors, so
  cross-jurisdiction resolution now spans a wider date range on the Ottawa
  side specifically.

## Vendor resolution

### Deterministic blocking and scoring; abstain, don't force, in the uncertain band

- Context: spec Part 8 wants deterministic blocking + `rapidfuzz` scoring
  for the bulk of pairs, with an LLM adjudicator reserved for the uncertain
  confidence band only.
- Decision: normalize (strip legal suffixes, punctuation, casing), block on
  normalized tokens, score with `rapidfuzz.token_set_ratio`. Pairs scoring
  above the upper threshold auto-match, below the lower threshold
  auto-reject; in between, abstain (`decision: None`) rather than force a
  match when no adjudicator is configured.
- Alternative rejected: forcing every uncertain pair into a match or
  non-match without an adjudicator backing the decision.
- Consequence: `entity_link` never fabricates certainty for a pair the
  scoring function is genuinely unsure about, and the adjudication band's
  width and hit rate are directly measurable
  (`evals/results/PROVISIONAL_resolution_metrics.log`). Known false
  positive from this same scoring function: `token_set_ratio` treats a name
  that's a strict token superset of another as a full match regardless of
  meaning (`docs/FAILURES.md` #17) — a real, disclosed precision limit, not
  hidden by the pipeline that uses it.

## Sources

### Ontario: the active VOR export, not the 2018–2020 planning outlook

- Context: the original Ontario source (`ontario_vor`, phase 1) was a
  39-row planned-opportunity outlook with no award values.
- Decision: use the official `enterprise_vor_program.csv` active VOR export
  instead — arrangement start/end dates and qualified-vendor names map
  directly; award amount stays unmapped/zero because the source publishes
  no per-transaction value at all.
- Alternative rejected: treating the planning outlook as representative of
  Ontario procurement volume.
- Consequence: Ontario's source expands to 1,822 active arrangements, but
  remains a standing-arrangement registry, not an award ledger — the $0
  amount must never be read as observed spend, and this is carried as a
  `coverage.known_gaps` entry, not left implicit.

### Two more federal/Ottawa sources; no second Ontario source

- Context: expanded source scope while staying within federal / Ontario /
  Ottawa (no new provinces or municipalities), adding real sources to
  jurisdictions already in scope where one could be verified.
- Decision: added `canadabuys_contract_history` (PWGSC/PSPC's full
  contract-history ledger — distinct from `canadabuys_award_notices`,
  which mirrors individual award-notice publications; licence verified via
  the CKAN API, same Open Government Licence family as the two existing
  federal sources) and `ottawa_historical_contracts` (above). Searched for
  a second Ontario source (ministry award notices / Broader Public Sector
  disclosure) — `data.ontario.ca`'s procurement-tagged catalogue surfaces
  only VOR-family datasets, and Ontario's tender portal is login-gated with
  no accompanying open-data export.
- Alternative rejected: approximating a second Ontario source from a
  different data shape, or fabricating one, to make jurisdiction coverage
  look more even. Per CLAUDE.md rule 3, no source proceeds without live
  verification and a confirmed licence.
- Consequence: 6 sources across the same 3 jurisdictions (federal now
  three-sourced, Ontario still single-sourced, Ottawa two-sourced by
  format/period). Ontario being thinner than the other two jurisdictions is
  a real, disclosed asymmetry, carried in `coverage.known_gaps` rather than
  masked by an approximated source.

### `openpyxl` dependency, and a `curl` fallback in `src/fetch.py`

- Context: `ottawa_historical_contracts` ships as `.xlsx`, which none of
  the previously-approved dependencies can read. Separately, fetching both
  new sources through `src/fetch.py` hit `403 Forbidden` from
  `canadabuys.canada.ca` and from ArcGIS-hosted downloads via Python's
  `urllib`, with or without a descriptive `User-Agent` — while `curl`'s
  default UA passed on both hosts. Reads as UA/TLS-fingerprint bot
  mitigation, not an access control the public licence doesn't already
  grant (the same URLs are the official download links).
- Decision: add `openpyxl` (minimal, standard, pure-Python `.xlsx` reader)
  as a new dependency, per the CLAUDE.md rule that anything beyond the
  approved stack needs an ADR — this is it. Changed `fetch()` to retry via
  a `curl` subprocess on `HTTPError`, and added a content-sniff that
  rejects a downloaded payload starting with `<html`/`<!doctype` (a silent
  200-status block page, hit once during this work), so that failure mode
  fails loudly instead of archiving garbage.
- Alternative rejected: hand-rolling `.xlsx` parsing via `zipfile` and raw
  XML to avoid a new dependency — unnecessary fragility for a well-solved
  problem. Also rejected: fetching these two sources by hand outside the
  archival convention, which would have left `src/fetch.py`'s
  timestamped-directory + sha256-sidecar convention unexercised again.
- Consequence: `src/fetch.py`'s archival convention is now actually
  exercised, with a real fallback for the CDN behavior it hit doing so. The
  four original sources' raw files remain un-migrated to this convention —
  re-fetching live feeds would change already-validated archived content,
  so they're left as they are rather than disturbed for consistency's sake.

## MCP agent

### Typed tools with rule-based refusal, not an LLM-judged refusal step

- Context: spec Part 9 requires five typed tools, no `run_sql`, confidence
  on every entity-touching tool, and coverage caveats — with refusal — on
  every aggregating tool.
- Decision: `src/agent_tools.py` holds plain, typed, pydantic-returning
  functions over the warehouse, unit-testable with no MCP or model
  dependency; `src/server.py` is a thin FastMCP wrapper with no logic of
  its own. Refusal is entirely rule-based: `cross_level_exposure` declines
  when an entity resolves to fewer than two jurisdictions, or when its
  weakest entity-link confidence falls below `resolve.UPPER_THRESHOLD`
  (reusing the resolution layer's existing auto-accept bar rather than
  inventing a second number); `compare_buyers` declines a per-buyer total
  below a 3-record sample floor. Sources whose matched records are all $0
  are excluded from dollar totals with an explicit caveat, never silently
  summed as zero.
- Alternative rejected: an LLM-adjudicated refusal step inside the tools
  themselves — the interpretive work of turning a declined-aggregate
  response into a spoken refusal belongs to whatever LLM is driving the
  tools (e.g. Claude Desktop), not baked into the tool. Also rejected: a
  custom chat UI — spec Part 3 scopes out any UI beyond a CLI/demo
  notebook, and any MCP client can already drive this server for free
  (`docs/AGENT_DEMO.md`), so a bespoke frontend would be new infrastructure
  this project's stack rules argue against.
- Consequence: verified against the live warehouse, not just fixtures —
  `cross_level_exposure` on a multi-jurisdiction entity (e.g. Stantec
  Consulting Ltd, resolved across all three levels) returns a real
  per-jurisdiction breakdown; the same tool on a single-jurisdiction entity
  (e.g. Kleenoil Filtration Canada Ltd, Ottawa-only) correctly declines
  with a stated reason instead of fabricating a cross-level number.

### Data browser: a static snapshot, not a live backend

- Context: wanted a clean way to browse the warehouse without building new
  infrastructure the "no server, no cloud infra" stack rule argues against.
- Decision: `scripts/export_snapshot.py` reads the warehouse read-only and
  produces a gzip+base64 JSON snapshot — every release, every
  cross-jurisdiction resolved entity (via the same `agent_tools` functions
  the MCP server uses, so the two surfaces can't drift apart in logic), and
  the coverage table. `demo/register_template.html` is a self-contained
  static page (one embedded variable font, vanilla JS, client-side
  `DecompressionStream`) with no server, no database connection, and no API
  calls at runtime. `scripts/build_register.py` merges the two into one
  ready-to-serve `demo/register.html`.
- Alternative rejected: a live web app backed by a running server and a
  connection to the warehouse — real hosting, auth, and maintenance surface
  for a piece that doesn't need to be live.
- Consequence: the browser is a point-in-time snapshot, not a live view —
  it goes stale the moment the warehouse changes and is regenerated on
  purpose (`uv run python scripts/build_register.py`), not automatically.
  `demo/*.b64`, `demo/coverage.json`, and the built `demo/register.html`
  are gitignored (derived data); the template, the two build scripts, and
  the committed font asset (`demo/assets/`) are what's actually versioned.

### Hosting: GitHub Pages (`gh-pages` branch), not a Claude Artifact

- Context: the data browser was first published as a Claude Artifact —
  quick to ship, but hosted on Anthropic's infrastructure rather than the
  project's own repo.
- Decision: publish the same built `demo/register.html` to a dedicated
  `gh-pages` branch (an orphan branch containing only `index.html`, kept
  separate from `main` so the actual source tree and `docs/` folder stay
  untouched) and serve it via GitHub Pages.
- Alternative rejected: keeping the Claude Artifact as the canonical link,
  or standing up a separate hosting account/service for one static file —
  GitHub Pages is free, requires no new account, and the repo was made
  public specifically to enable it.
- Consequence: the browser now lives at
  `https://adamkaegi.github.io/procurement-resolver/`, under this repo's
  own control. Republishing after a warehouse change is a manual, two-step
  build-then-push (`scripts/build_register.py`, then copy the output into
  a `gh-pages` worktree and push) — deliberately manual, same reasoning as
  the snapshot-not-live-view decision above.
