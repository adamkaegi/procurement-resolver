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