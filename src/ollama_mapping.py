"""Real LLM-backed mapping generation via a local Ollama model.

Companion to generate_mapping.py's offline deterministic scaffold. That
module has never called a model at all (see docs/DECISIONS.md, "Real LLM
calls for mapping generation"); this one actually does, against a locally
running Ollama server rather than a hosted API (Adam's choice -- no API key
needed, zero marginal cost per call, per the LLM usage policy's "log tokens,
cost, and latency" requirement: cost is genuinely $0.0 here, not "no model
configured").

Requires `ollama serve` running locally with the requested model already
pulled (`ollama list` to check). Not exercised by pytest: this repo's own
convention is that tests measure code correctness and evals measure model
behaviour (CLAUDE.md, "Conventions") -- a live local model call belongs to
the eval/generation side, not the deterministic test suite.

Usage:
    uv run python -m src.ollama_mapping \\
        --source-id canadabuys_contract_history --jurisdiction federal \\
        --sample data/raw/canadabuys_contract_history/<ts>/contractHistory-2024-2025.csv \\
        --output sources/canadabuys_contract_history/mapping.yaml \\
        --log evals/results/llm_calls.jsonl
"""

import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .generate_mapping import CANONICAL_FIELDS, validate_mapping, validate_sample
from .transform_registry import TRANSFORMS

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
MAX_ATTEMPTS = 3

EXAMPLE_MAPPING = {
    "source_id": "example_source",
    "mappings": [
        {"canonical": "ocid", "disposition": "mapped", "source_field": "someSolicitationIdColumn",
         "transform": "direct_or_reference", "confidence": "high", "reasoning": "why this column is the ocid"},
        {"canonical": "awards[].items[].classification.id", "disposition": "derived",
         "source_fields": ["unspsc", "gsin"], "transform": "first_present", "confidence": "medium",
         "reasoning": "two candidate columns, take whichever is present"},
        {"canonical": "buyer.id", "disposition": "unmapped", "transform": "unmapped", "confidence": "high",
         "reasoning": "no stable buyer identifier is published"},
    ],
}


def _build_prompt(source_id: str, fields: list[str], sample_rows: list[dict[str, str]]) -> str:
    sample_preview = json.dumps(sample_rows[:3], indent=2, ensure_ascii=False)
    return f"""You are generating a field mapping from a real government open-data CSV to a fixed canonical schema. Respond with ONLY a single JSON object, no prose before or after it.

Source id: {source_id}

Every one of these canonical fields must appear exactly once in your "mappings" list:
{json.dumps(CANONICAL_FIELDS)}

For each canonical field, choose "disposition":
- "mapped": exactly one source column is the answer -> set "source_field" (a string, must be one of the real column names below, exactly as spelled).
- "derived": more than one source column could supply it (e.g. a value with a fallback column) -> set "source_fields" (a list of real column names, most-preferred first).
- "unmapped": no real column in this source answers it -> omit source_field/source_fields.

Every single mapping entry, INCLUDING every "unmapped" one, MUST still include a "transform" key. For "unmapped" entries always set "transform": "unmapped" -- never omit the transform key.

"transform" must be one of exactly these registered names (do not invent others):
{json.dumps(sorted(TRANSFORMS.keys()))}

"confidence" must be "high", "medium", or "low". "reasoning" is one short sentence explaining your choice using the real column names and sample values below -- not a generic sentence.

The real column names in this CSV (use these exact strings, do not translate, abbreviate, or guess column names that aren't in this list):
{json.dumps(fields)}

Three real sample rows from this CSV, so you can see what values actually look like:
{sample_preview}

Output format -- follow this shape exactly (this is a different, smaller source, just showing the shape):
{json.dumps(EXAMPLE_MAPPING, indent=2)}

Respond with ONLY the JSON object for source_id="{source_id}" covering every canonical field listed above."""


def _call_ollama(prompt: str, model: str, host: str) -> tuple[dict[str, Any], float]:
    body = json.dumps({"model": model, "prompt": prompt, "format": "json", "stream": False, "options": {"temperature": 0.1}}).encode()
    request = urllib.request.Request(f"{host}/api/generate", data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read())
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return payload, elapsed_ms


def generate_with_model(
    source_id: str, jurisdiction: str, sample_path: Path, output_path: Path, log_path: Path,
    model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    with sample_path.open(newline="", encoding=encoding) as stream:
        reader = csv.DictReader(stream)
        sample = list(reader)
        fields = reader.fieldnames or []
    prompt = _build_prompt(source_id, fields, sample)

    mapping: dict[str, Any] | None = None
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        payload, elapsed_ms = _call_ollama(prompt, model, host)
        raw_text = payload.get("response", "")
        try:
            mapping = json.loads(raw_text)
        except json.JSONDecodeError as error:
            errors = [f"model response was not valid JSON: {error}"]
            mapping = None
        else:
            mapping["source_id"] = source_id
            mapping["model"] = f"ollama/{model}"
            mapping["generated_at"] = datetime.now(timezone.utc).isoformat()
            # apply_mapping.py's _release() reads config["mapping_version"]
            # and config["jurisdiction"] unconditionally (KeyError
            # otherwise) -- these are caller-known constants, not something
            # to ask the model to invent.
            mapping["mapping_version"] = f"phase-6-llm-{model}"
            mapping["jurisdiction"] = jurisdiction
            errors = validate_mapping(mapping, fields)
            errors.extend(validate_sample(mapping, sample[:20]))
        events.append({
            "source_id": source_id, "model": f"ollama/{model}", "attempt": attempt,
            "input_tokens": payload.get("prompt_eval_count", 0), "output_tokens": payload.get("eval_count", 0),
            "cost_usd": 0.0, "cost_note": "local inference via Ollama, no metered API cost",
            "latency_ms": elapsed_ms, "validation_outcome": "passed" if not errors else "failed",
            "errors": errors, "raw_response_head": raw_text[:2000],
        })
        if not errors:
            break

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")

    if errors:
        raise ValueError(f"model mapping did not pass validation after {len(events)} attempt(s): " + "; ".join(errors))
    assert mapping is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(mapping, sort_keys=False))
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()
    mapping = generate_with_model(args.source_id, args.jurisdiction, args.sample, args.output, args.log, args.model, args.host, args.encoding)
    print(json.dumps(mapping, indent=2))


if __name__ == "__main__":
    main()
