# Cross-Jurisdictional Procurement Resolver — Project Specification

**Author:** Adam Kaegi
**Version:** 2 (narrowed to the National Capital Region; agent layer added)
**Purpose of this document:** two audiences. Mentors should read Parts 1–3 and answer the questions in Part 11. Claude Code should read Parts 4–10 and start at Part 10.

> This is the original design spec, written and committed before the build
> started, and left as-written below — including Part 13's placeholder
> figures, which stay placeholders on purpose (Part 12: "no metric appears
> anywhere until `run_eval.py` produced it"). For what actually exists today,
> see [`README.md`](../README.md) and [`docs/PROGRESS.md`](PROGRESS.md).

---

## Part 1 — Thesis

Canadian public procurement is published at three levels of government that share no schema, no vendor identifier, and no common publication format. A vendor holding contracts at all three levels is invisible as a single entity to every existing system.

This project builds two things:

1. **An adapter layer** that ingests federal, Ontario, and City of Ottawa procurement data into one canonical schema, with LLM-generated field mappings and cross-jurisdictional vendor resolution.
2. **An agent** that answers cross-jurisdictional questions over the resolved data, and refuses to answer when the resolution underneath is too weak to support a claim.

The domain is a corpus, not the point. The same shape appears when consolidating ERPs after an acquisition, joining claims across carriers, or reconciling provider registries across hospital systems: different vocabularies for the same entities, no common key, and one team with a week to make it queryable.

**Two claims to earn:**
- A new source can be onboarded in under 20 minutes for under $1, at a measured field-level precision and a measured silent-error rate.
- The agent answers cross-jurisdictional questions with resolution confidence attached, and correctly declines the questions the data cannot support.

---

## Part 2 — Why the National Capital Region

The geographic narrowing is a design decision, not a scope cut.

**Dense genuine overlap.** Ottawa is the one Canadian city where federal, provincial, and municipal procurement pools draw on substantially the same local vendor base. An IT services or engineering firm in the region can hold a PSPC contract, an Ontario ministry arrangement, and a City of Ottawa award concurrently. Cross-level entity resolution therefore produces *real* joins rather than coincidental name similarity across unrelated markets.

**Three genuinely different failure modes in one footprint.**

| Level | Publication form | What breaks |
|---|---|---|
| Federal | Bulk CSV / JSON, documented | Free-text vendor names entered by ~80 departments |
| Ontario | Open data catalogue datasets, notice postings | Partial coverage, threshold-driven gaps, inconsistent vocabulary |
| Ottawa | Delegation of Authority reports tabled at committee | Semi-structured documents, not datasets |

**Thresholds differ by level and create structural gaps.** Federal proactive disclosure covers contracts over $10,000. Ontario's OPS Procurement Directive requires award notifications at $25,000 for goods and $100,000 for services. Ottawa's Delegation of Authority reports cover procurements over $25,000, with a separate Council policy on proactive disclosure of awards of $100,000 or more of significant public interest.

These thresholds are a first-class finding. Any cross-jurisdictional total is comparing three differently-censored populations. The agent must know this and say so. **This single fact is the best argument in the project for why an agent with coverage awareness beats a dashboard.**

**A standard exists and was abandoned.** OCDS is the international open standard for publishing public contracting data. PSPC piloted it with roughly 250 contract records under the 2018–2020 National Action Plan on Open Government; their own report concedes the pilot was not a compliant release, and the dataset is now archived. Ontario and Ottawa never adopted it. The target schema is therefore published and real, not invented, and the project measures what automated retrofitting costs.

---

## Part 3 — Scope

### In scope
- Ingest 7–8 sources across federal / Ontario / Ottawa into a canonical OCDS subset
- LLM-generated source-to-canonical field mappings, reviewed once per source and committed as config
- Document extraction for the Ottawa municipal layer
- Cross-jurisdictional vendor entity resolution with confidence scores and evidence
- An MCP server exposing typed tools over the resolved data
- An agent that answers cross-level questions and refuses below a confidence threshold
- Two eval harnesses: mapping quality, and agent tool-use / refusal behaviour
- Cost and latency instrumentation per source onboarded
- A written failure analysis

### Explicitly out of scope
- Any province other than Ontario; any municipality other than Ottawa
- Any login-walled or commercially licensed source (MERX, Biddingo, bids&tenders — terms of service)
- Real-time or scheduled ingestion. Batch, run manually
- A user-facing UI beyond a CLI and a demo notebook
- Directors / beneficial-ownership graph. Registry linkage is limited to name resolution only
- French-language sources. Dropped with the other provinces; note this removes a whole failure class from the eval

### Success criteria
1. Seven or more sources ingest and validate against the canonical schema.
2. At least three sources were mapped by the generator and never hand-corrected.
3. A hand-labelled gold set exists for mapping quality and for vendor resolution, both committed before the corresponding system was built.
4. `cli eval` reproduces all headline metrics from one command.
5. The agent answers a cross-level question with confidence attached, and declines a question the coverage cannot support, in the same demo.
6. The failure analysis names at least ten specific failures with root causes.

---

## Part 4 — Data sources

**Do not hardcode URLs from this document.** Verify each source is live and confirm its licence before writing an adapter. Most of these are published under the Open Government Licence – Canada, which permits reuse with attribution; confirm and record per source in `source.yaml`.

| # | Source | Level | Form | Role |
|---|---|---|---|---|
| 1 | Proactive disclosure of contracts over $10K (Treasury Board) | Federal | Bulk CSV | Primary federal award data; dirtiest vendor names |
| 2 | CanadaBuys award notices | Federal | CSV + XML data dictionary | Publisher documents inconsistent field capture across upstream systems |
| 3 | CanadaBuys contract history | Federal | CSV by fiscal year | Historical depth; overlapping and partially redundant with #1 |
| 4 | CanadaBuys archived OCDS pilot | Federal | JSON (OCDS) | **Schema ground truth.** Already in target form |
| 5 | Ontario Open Government Catalogue procurement datasets | Provincial | CSV/API | Provincial vocabulary; includes VOR arrangement data |
| 6 | Ontario ministry contract award notifications | Provincial | Notice postings | Threshold-gated coverage; likely HTML |
| 7 | City of Ottawa Delegation of Authority reports | Municipal | **PDF / HTML committee documents** | Document extraction problem, not a mapping problem |
| 8 | Open Ottawa portal (procurement-adjacent datasets) | Municipal | CSV/API | Supplementary; drop if thin |

**Volume cap:** ~5,000 records per source. This is not a big-data project.

**Registry anchor (optional, decide in Phase 2):** the ISED federal corporations bulk download gives legal names and corporation numbers. It only covers federally incorporated entities, so Ontario-incorporated firms will be absent. If used, report registry-anchored and vendor-to-vendor resolution as **separate modes with separate metrics**. Do not blend them.

**Source triage rule.** If a source takes more than two hours to yield any structured data, drop it and document why. A source that defeated the approach is a legitimate finding.

---

## Part 5 — Canonical schema

A deliberate subset of **OCDS 1.1**. Awards and contracts only; no planning or implementation stages.

```
ocid                       string    globally unique contracting process id
id                         string    release id
date                       datetime
initiationType             string    "tender"
tag                        [string]  ["award"] | ["contract"]
buyer.name                 string
buyer.id                   string    scheme-qualified where available
buyer.jurisdiction         string    EXTENSION: "federal" | "on" | "ottawa"
awards[].id                string
awards[].date              datetime
awards[].value.amount      number
awards[].value.currency    string    ISO 4217
awards[].suppliers[].name  string    as published, never normalized in place
awards[].suppliers[].id    string    nullable
awards[].items[].classification.scheme  string
awards[].items[].classification.id      string
awards[].description       string    nullable
contracts[].period.startDate  datetime  nullable
contracts[].period.endDate    datetime  nullable
```

### Provenance block (required on every record)
```
_provenance.source_id        string
_provenance.fetched_at       datetime
_provenance.mapping_version  string    git sha of the mapping config
_provenance.raw_ref          string    pointer to archived raw payload
_provenance.field_origins    object    canonical field -> source field name
_provenance.extraction_conf  number    nullable; set for document-extracted records
```

### Resolved entity store (separate table, never overwrites source data)
```
entity_id             string
canonical_name        string
name_variants         [string]
registry_id           string    nullable; corporation number if anchored
resolution_mode       string    "registry" | "vendor_to_vendor"
```
```
entity_link
  entity_id           string
  source_id           string
  source_vendor_name  string    verbatim
  confidence          number    0.0–1.0
  method              string    "exact" | "normalized" | "fuzzy" | "llm_adjudicated"
  evidence            object    what drove the match
```

**Rule:** the source record is immutable. Resolution is a link table pointing at it. Anything downstream that reads an entity reads its links and their confidences.

### Coverage table (required — drives agent refusals)
```
coverage
  source_id, jurisdiction, date_range_start, date_range_end,
  value_threshold, record_count, known_gaps [string]
```
This is where the $10K / $25K / $100K threshold differences are encoded. Without it, the agent cannot honestly compare levels.

---

## Part 6 — Architecture

```
procurement-resolver/
  README.md
  pyproject.toml
  data/
    raw/<source_id>/<fetch_timestamp>/     immutable archived payloads
    warehouse.duckdb                        gitignored, rebuildable
  schema/
    ocds_subset.json
    codelists/{currency,procurement_method,unspsc_segments}.csv
  sources/
    <source_id>/
      source.yaml       fetch config, licence, jurisdiction, thresholds, notes
      mapping.yaml      GENERATED then reviewed — the core artifact
      transform.py      escape hatch; expected for the Ottawa source
  src/
    fetch.py
    generate_mapping.py     LLM: schema induction, once per source
    extract_documents.py    LLM: document -> structured records (Ottawa)
    apply_mapping.py
    validate.py
    resolve.py              blocking, scoring, LLM adjudication band
    load.py
    coverage.py
    server.py               MCP server (FastMCP)
    cli.py
  evals/
    gold/
      mappings/<source_id>.mapping.yaml
      resolution/pairs.csv                 ~200 labelled vendor pairs
      agent/questions.yaml                 ~40 questions in 3 buckets
    run_eval.py
    results/                                committed, timestamped
  docs/
    WRITEUP.md
    DECISIONS.md                            ADR log
```

### Pipeline
```
fetch → archive raw → generate mapping (once/source) → human review
      → apply mapping → validate → load
      → resolve entities → build coverage table
      → MCP server → agent → eval
```

### The hard rule on LLM usage
**Per source, not per row — with one deliberate exception.**

Mapping generation runs once per source and its output is committed, diffable config. Applying that mapping is deterministic code.

The exception is Ottawa document extraction, which is necessarily per document. That exception is the interesting part of the cost analysis: report federal/Ontario onboarding cost and Ottawa extraction cost **separately**, because they are different economic regimes and conflating them hides the finding.

Entity resolution is deterministic for the bulk (blocking + `rapidfuzz`) with LLM adjudication only in the uncertain confidence band. Log the band width and the proportion of pairs falling into it.

Write an ADR in `docs/DECISIONS.md` every time deterministic logic is chosen over an LLM call or vice versa. These entries are the source material for the writeup.

---

## Part 7 — The mapping generator

### Input
Source's `source.yaml`; ~20 raw sample records; any publisher data dictionary; the canonical schema and codelists.

### Output contract
Strict YAML, no prose or fences. Every canonical field gets one of three dispositions.

```yaml
source_id: ontario_vor
generated_at: 2026-09-09T14:22:00Z
model: claude-sonnet-4-6
mappings:
  - canonical: awards[].value.amount
    disposition: mapped
    source_field: CONTRACT_VALUE
    transform: parse_currency
    confidence: high
    reasoning: "Currency-formatted numeric; magnitude distribution consistent with award values"

  - canonical: awards[].items[].classification.id
    disposition: derived
    source_fields: [COMMODITY_DESCRIPTION]
    transform: unspsc_lookup
    confidence: medium
    reasoning: "No code present; free-text description requires lookup"

  - canonical: contracts[].period.endDate
    disposition: unmapped
    confidence: high
    reasoning: "No end-date field present in this source"
```

### Rules the generator must follow
1. **Abstention is a correct answer.** `unmapped` with sound reasoning scores better than a wrong guess. State this explicitly in the prompt.
2. Never invent a source field name. Every `source_field` must appear verbatim in the sample.
3. `transform` must name a function in a fixed registry. Unknown transforms fail validation.
4. Every mapping carries reasoning. That is what a human reviews.

### Validation gate
YAML parses and matches the mapping schema · every `source_field` exists in raw data · every `transform` is registered · applying it to the sample produces records passing OCDS subset validation · dates parse, amounts are numeric and non-negative, currency is ISO 4217.

One retry with the error attached. A second failure counts as a generator failure in the eval.

### Instrumentation
Per generation: wall-clock, input/output tokens, cost, retries, validation outcome. These are the headline numbers.

---

## Part 8 — Entity resolution

### Pipeline
1. **Normalize** legal suffixes (Inc./Incorporated/Ltd./Limited/Corp.), punctuation, casing, whitespace. Store normalized form alongside the verbatim name; never overwrite the original.
2. **Block** on normalized tokens to avoid an all-pairs comparison.
3. **Score** candidate pairs with `rapidfuzz`.
4. **Band** the scores: auto-accept above the upper threshold, auto-reject below the lower, LLM adjudication in between.
5. **Adjudicate** the middle band with an LLM that receives both verbatim names, both jurisdictions, both buyer contexts, and any registry candidate — and must return a decision plus evidence, with abstention permitted.
6. **Link**, never merge. Write to `entity_link` with confidence and method.

### Known-hard cases to catalogue deliberately
- Numbered companies (`1234567 Ontario Inc.`) with no distinguishing text
- Operating-name vs legal-name divergence
- Subsidiary vs parent (`X Canada Inc.` vs `X Holdings Ltd.`)
- Divisions of the same firm bidding at different levels
- Data-entry corruption in federal free-text vendor fields
- Ontario-incorporated firms absent from the federal registry

Each of these is a row in the failure catalogue. Ten-plus specific failures with root causes is a deliverable.

### Metrics
Precision and recall against the gold pair set, **broken out by jurisdiction pair** (federal↔Ontario, federal↔Ottawa, Ontario↔Ottawa), plus adjudication band width, proportion of pairs adjudicated, and cost per adjudicated pair. Report absolute counts alongside every percentage.

---

## Part 9 — The agent

### Design rule
**No `run_sql` tool.** Text-to-SQL is impressive for thirty seconds and impossible to evaluate. Typed tools only.

Every tool that touches an entity returns resolution confidence alongside the answer. Every tool that aggregates returns coverage caveats. Uncertainty from Part 8 propagates into the answer as a first-class field — that is the through-line of the whole project.

### Tools
| Tool | Returns |
|---|---|
| `resolve_vendor(name, jurisdiction?)` | ranked entity candidates, confidence, evidence |
| `entity_profile(entity_id)` | contracts across all three levels, per-link confidence, verbatim source names |
| `cross_level_exposure(entity_id)` | totals by jurisdiction, **with threshold caveats attached** |
| `compare_buyers(category, jurisdictions[])` | aggregates plus coverage caveats |
| `coverage(jurisdiction?, date_range?)` | what the system actually holds, thresholds, known gaps |

`coverage` is the tool most people would not build and the one that makes honest refusal possible.

### Refusal behaviour
Below a configured confidence threshold, `cross_level_exposure` and `compare_buyers` return candidates and decline to aggregate. The agent's job is then to explain why. Cross-jurisdictional totals are exactly where a confident wrong answer does the most damage, because unified-looking data hides a guessed join.

### Agent eval
Forty questions in three buckets:
- **A — answerable.** Resolution is strong and coverage supports it.
- **B — answerable with a caveat.** The answer requires stating a threshold or coverage gap.
- **C — unanswerable.** Coverage or resolution cannot support it.

Measure: tool-selection accuracy, answer correctness on A, caveat-presence rate on B, and **refusal rate on C**.

Bucket C is the differentiator. Almost no portfolio agent has one.

---

## Part 10 — Build plan

Seven weekends. Each phase has an acceptance test; do not proceed until it passes.

### Phase 0 — Foundations (½ day)
Scaffold repo, pin deps, write `ocds_subset.json`.
**Accept when:** the archived CanadaBuys OCDS pilot data validates against your subset. If it doesn't, the subset is wrong. This is why source #4 exists.

### Phase 1 — Manual adapters (weekend 1)
Hand-write `mapping.yaml` for three sources: one federal, one Ontario, one simple. No LLM yet.
**Accept when:** all three ingest, validate, load; one SQL query returns records from all three with provenance intact.
> You cannot evaluate generated mappings until you know what a correct one looks like. Skipping this is the most likely way the project goes wrong.

### Phase 2 — Gold sets (weekend 2)
Hand-label: correct mappings for two held-out sources, ~200 vendor pairs across all three jurisdiction pairings, and the 40 agent questions.
**Accept when:** all three gold artifacts are committed, **before** the corresponding systems exist.
> The least enjoyable weekend and the only reason any number in the writeup means anything. Do not label after seeing model output.

### Phase 3 — Mapping generator (weekend 3)
`generate_mapping.py`, transform registry, validation gate.
**Accept when:** it reproduces the three hand-written mappings at a measurable rate and produces a passing mapping for one held-out source with no human edits.

### Phase 4 — Ottawa document extraction (weekend 4)
`extract_documents.py` against Delegation of Authority reports.
**Accept when:** extracted records validate, carry `extraction_conf`, and per-document cost is logged.
> Highest-risk phase. If the reports resist extraction, cap effort at one weekend, report the failure honestly, and proceed with two levels instead of three. A documented failure beats a slipped timeline.

### Phase 5 — Resolution (weekend 5)
`resolve.py`, entity store, coverage table.
**Accept when:** precision/recall reported by jurisdiction pair against the gold pairs, with absolute counts.

### Phase 6 — MCP server and agent (weekend 6)
`server.py`, tools, refusal logic, agent eval harness.
**Accept when:** `cli eval` outputs mapping metrics, resolution metrics, and agent metrics from one command.

### Phase 7 — Confidence gating and writeup (weekend 7)
Sweep thresholds on both the mapping and resolution layers. Plot silent-error rate against abstention rate.
**Accept when:** you can state *"gating at X cut silent errors from A% to B% at the cost of C% abstention"* — the strongest single line in the writeup.

`docs/WRITEUP.md` structure: one concrete failure and its downstream cost → the design decision that came out of it → the numbers → the ten-plus failure catalogue → how this generalizes beyond procurement → architecture last, if at all.

### Headline metrics
| Metric | Definition |
|---|---|
| Field precision | correct mappings / mappings proposed |
| Field recall | correct mappings / mappings existing in gold |
| Abstention rate | fields correctly marked `unmapped` |
| **Silent-error rate** | mappings passing all validation but disagreeing with gold |
| Resolution P/R | by jurisdiction pair, with counts |
| Agent refusal rate | correct declines on bucket C |
| Cost & latency | per source onboarded; Ottawa extraction reported separately |

---

## Part 11 — Questions for mentors

**Framing**
1. Is "silent-error rate" legible to someone who hasn't read this spec, or does it need renaming?
2. Does a procurement corpus read as civic-tech in a way that hurts at non-government-facing employers? Is one paragraph of generalization enough?
3. Do the resume lines in Part 13 hook, or read as a data-engineering task?

**Scope**
4. Seven weekends while job hunting. Which phase would you cut first? My answer is Phase 4 (Ottawa extraction) — is that right, or does losing the third level gut the premise?
5. Is narrowing to one metro the right call, or does it look small next to a multi-province version?
6. Should this be deployed, or is a reproducible local build enough?

**Rigor**
7. Is ~200 labelled pairs and two held-out sources enough to state percentages?
8. Am I fooling myself anywhere — is there a path where this produces good-looking numbers that don't mean anything?
9. Is the threshold-difference problem ($10K / $25K / $100K) handled honestly by putting it in a coverage table, or does it undermine cross-level comparison entirely?

**The known gap**
10. This project has no users. Is that fatal for an FDE application, and what's the cheapest way to get two or three real ones?

---

## Part 12 — Risks

| Risk | Mitigation |
|---|---|
| Ottawa reports resist extraction | Cap at one weekend; report as a finding; ship with two levels |
| Threshold differences make totals misleading | Coverage table; agent must attach caveats; never aggregate silently across levels |
| Federal registry misses Ontario-incorporated firms | Report registry-anchored and vendor-to-vendor resolution as separate modes |
| Sources move or go offline | Archive raw on first fetch; never re-fetch for reproducibility |
| Licence or ToS problems | Open-licensed sources only; verify and record per source |
| Gold set too small | Report absolute counts alongside every percentage |
| Gold set contaminated | Label and commit before building the corresponding system |
| Scope creep (directors graph, other provinces, UI) | Part 3 cuts are binding; revisit only after Phase 7 ships |
| Numbers quoted before earned | **No metric appears anywhere until `run_eval.py` produced it.** |
| Dropping French removes a failure class | Acknowledge explicitly in the writeup as a limitation, not an omission |

---

## Part 13 — The resume lines

Draft. **All figures are placeholders until the eval harness produces them.**

> **Cross-Jurisdictional Procurement Resolver** — Unified federal, Ontario, and City of Ottawa contract data (7 sources, CSV to committee PDFs) into one OCDS schema using LLM-generated adapters; resolved vendors across jurisdictions at 91% precision with confidence propagated to every answer. MCP agent answers cross-level exposure questions and correctly declines 87% of questions the coverage can't support.

---

## Part 14 — Notes for Claude Code

- Start at **Phase 0**. Phases 1 and 2 are prerequisites for everything else; the project fails without them.
- Verify every source URL is live before writing an adapter. Do not trust URLs in this document.
- Record each source's licence in `source.yaml` before ingesting.
- DuckDB only. Single file, no server, no infra.
- Archive raw payloads immutably under `data/raw/`. Never modify them.
- Source records are immutable. Resolution writes to `entity_link`; it never rewrites a vendor name in place.
- Every LLM call logs tokens, cost, and latency to a structured file. This is a deliverable, not debug output.
- Report federal/Ontario onboarding cost and Ottawa per-document extraction cost separately. Never blend them.
- Commit all gold-set files before implementing the systems they evaluate: mappings before `generate_mapping.py`, pairs before `resolve.py`, questions before `server.py`.
- Write an ADR in `docs/DECISIONS.md` at every deterministic-vs-LLM decision point.
- No `run_sql` tool on the MCP server. Typed tools only.
