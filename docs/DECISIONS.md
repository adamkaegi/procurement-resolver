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

## Phase 1 resumed: active Ontario VOR export

- Context: The original Ontario VOR outlook contained only 39 planned opportunities and no award values; the page itself pointed to a separate active-arrangements export.
- Decision: Use the official `enterprise_vor_program.csv` active VOR export as the Ontario adapter input. Map qualified vendors and arrangement start/end dates, and keep award amount unknown as zero because the source does not publish transaction values.
- Alternative rejected: treating the planning outlook as representative of Ontario procurement volume.
- Consequence: the Ontario source expands to 1,822 active arrangements, but it remains an arrangement registry rather than an award ledger and must carry that coverage caveat.