"""Tests for src/ollama_mapping.py's deterministic, network-free parts.

Deliberately does NOT call a live Ollama server: per CLAUDE.md
"Conventions", tests measure code correctness and evals measure model
behaviour -- this repo's actual model call (logged in
evals/results/llm_calls.jsonl) is the eval, not something pytest re-runs.

test_example_mapping_is_internally_consistent exists because of a real bug
caught mid-session: the prompt's own worked example showed an "unmapped"
entry with no "transform" key, and the model faithfully copied that shape
on every attempt, failing validation three times before the example (not
the model) was fixed. This pins that shape so it can't regress silently.
"""

from src.generate_mapping import CANONICAL_FIELDS
from src.ollama_mapping import EXAMPLE_MAPPING, _build_prompt
from src.transform_registry import TRANSFORMS


def test_example_mapping_is_internally_consistent():
    for item in EXAMPLE_MAPPING["mappings"]:
        assert "transform" in item, f"{item['canonical']} is missing transform -- the model will copy this shape"
        assert item["transform"] in TRANSFORMS
        if item["disposition"] == "unmapped":
            assert item["transform"] == "unmapped"
            assert "source_field" not in item and "source_fields" not in item
        if item["disposition"] == "mapped":
            assert "source_field" in item
        if item["disposition"] == "derived":
            assert "source_fields" in item


def test_build_prompt_includes_canonical_fields_registered_transforms_and_real_columns():
    fields = ["realColumnA", "realColumnB"]
    sample_rows = [{"realColumnA": "value1", "realColumnB": "value2"}]
    prompt = _build_prompt("test_source", fields, sample_rows)

    for canonical in CANONICAL_FIELDS:
        assert canonical in prompt
    for transform in TRANSFORMS:
        assert transform in prompt
    assert "realColumnA" in prompt
    assert "value1" in prompt
    assert "test_source" in prompt
    # the exact bug this module's other test pins: the prompt text itself
    # must tell the model transform is required even when unmapped.
    assert "transform" in prompt.lower()
