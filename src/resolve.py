"""Deterministic vendor resolution, entity links, coverage, and evaluation."""

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import yaml
from rapidfuzz import fuzz


LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "llc", "lp", "llp", "of canada",
}
UPPER_THRESHOLD = 92.0
LOWER_THRESHOLD = 65.0


def normalize_vendor(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).lower()
    tokens = text.split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def block_key(name: str) -> str:
    normalized = normalize_vendor(name)
    numbered = re.match(r"(\d+)", normalized)
    if numbered:
        return f"numbered:{numbered.group(1)}"
    tokens = normalized.split()
    return tokens[0] if tokens else "empty"


def score_names(left: str, right: str) -> float:
    if normalize_vendor(left) == normalize_vendor(right):
        return 100.0
    return float(fuzz.token_set_ratio(normalize_vendor(left), normalize_vendor(right)))


def classify_pair(left: str, right: str, adjudicator: Any = None) -> dict[str, Any]:
    score = score_names(left, right)
    if score >= UPPER_THRESHOLD:
        decision, method = True, "exact" if score == 100 else "normalized"
    elif score <= LOWER_THRESHOLD:
        decision, method = False, "fuzzy"
    elif adjudicator is not None:
        result = adjudicator(left, right)
        if result is None:
            decision, method = None, "llm_adjudicated"
        else:
            decision, method = bool(result), "llm_adjudicated"
    else:
        decision, method = None, "llm_adjudicated"
    return {
        "decision": decision,
        "score": round(score, 3),
        "confidence": round(score / 100, 3),
        "method": method,
        "evidence": {"normalized_left": normalize_vendor(left), "normalized_right": normalize_vendor(right), "block_left": block_key(left), "block_right": block_key(right)},
    }


def rank_candidates(name: str, candidates: list[dict[str, str]], limit: int = 10) -> list[dict[str, Any]]:
    """Return scored candidates from the same normalized blocking bucket."""
    bucket = block_key(name)
    ranked = []
    for candidate in candidates:
        if block_key(candidate["source_vendor_name"]) != bucket:
            continue
        result = classify_pair(name, candidate["source_vendor_name"])
        ranked.append({**candidate, **result})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]


def evaluate_pairs(pair_path: Path, output_path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]]
    with pair_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "abstained": 0, "total": 0})
    adjudicated = 0
    for row in rows:
        result = classify_pair(row["vendor_a"], row["vendor_b"])
        expected = row["label"] == "match"
        predicted = result["decision"] is True
        pair_key = "<->".join(sorted((row["jurisdiction_a"], row["jurisdiction_b"])))
        counts = grouped[pair_key]
        counts["total"] += 1
        if result["decision"] is None:
            counts["abstained"] += 1
        elif predicted and expected:
            counts["tp"] += 1
        elif predicted and not expected:
            counts["fp"] += 1
        elif not predicted and expected:
            counts["fn"] += 1
        else:
            counts["tn"] += 1
        if result["method"] == "llm_adjudicated":
            adjudicated += 1

    metrics: dict[str, Any] = {}
    for pair_key, counts in grouped.items():
        precision_denominator = counts["tp"] + counts["fp"]
        recall_denominator = counts["tp"] + counts["fn"]
        metrics[pair_key] = {
            **counts,
            "precision": counts["tp"] / precision_denominator if precision_denominator else None,
            "recall": counts["tp"] / recall_denominator if recall_denominator else None,
        }
    result = {
        "evaluation": "PROVISIONAL",
        "pairs_path": str(pair_path),
        "metrics_by_jurisdiction_pair": metrics,
        "adjudication_band": {"lower_exclusive": LOWER_THRESHOLD, "upper_exclusive": UPPER_THRESHOLD, "pairs_adjudicated": adjudicated, "proportion_adjudicated": adjudicated / len(rows) if rows else 0.0, "cost_usd": 0.0},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as stream:
        stream.write("PROVISIONAL\n")
        stream.write(json.dumps(result, indent=2) + "\n")
    return result


def _entity_id(normalized: str) -> str:
    return "ent_" + hashlib.sha1(normalized.encode()).hexdigest()[:16]


def build_entity_store(database: Path, project_root: Path) -> None:
    with duckdb.connect(str(database)) as connection:
        records = connection.execute("SELECT source_id, record FROM releases").fetchall()
        vendors: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for source_id, raw_record in records:
            record = json.loads(raw_record)
            for award in record.get("awards", []):
                for supplier in award.get("suppliers", []):
                    name = supplier.get("name", "")
                    if name:
                        vendors[normalize_vendor(name)].append((source_id, name))
        connection.execute("DROP TABLE IF EXISTS entity_link")
        connection.execute("DROP TABLE IF EXISTS entity")
        connection.execute("DROP TABLE IF EXISTS coverage")
        connection.execute("CREATE TABLE entity (entity_id VARCHAR, canonical_name VARCHAR, name_variants JSON, registry_id VARCHAR, resolution_mode VARCHAR)")
        connection.execute("CREATE TABLE entity_link (entity_id VARCHAR, source_id VARCHAR, source_vendor_name VARCHAR, confidence DOUBLE, method VARCHAR, evidence JSON)")
        connection.execute("CREATE TABLE coverage (source_id VARCHAR, jurisdiction VARCHAR, date_range_start VARCHAR, date_range_end VARCHAR, value_threshold DOUBLE, record_count INTEGER, known_gaps JSON)")
        for normalized, links in vendors.items():
            entity_id = _entity_id(normalized)
            canonical_name = links[0][1]
            variants = sorted({name for _, name in links})
            connection.execute("INSERT INTO entity VALUES (?, ?, ?, NULL, ?)", [entity_id, canonical_name, json.dumps(variants), "vendor_to_vendor"])
            for source_id, name in links:
                evidence = {"normalized_name": normalized, "blocking": "exact_normalized"}
                connection.execute("INSERT INTO entity_link VALUES (?, ?, ?, ?, ?, ?)", [entity_id, source_id, name, 1.0, "normalized", json.dumps(evidence)])
        for source_file in sorted((project_root / "sources").glob("*/source.yaml")):
            config = yaml.safe_load(source_file.read_text())
            if config.get("role") == "schema_ground_truth":
                # e.g. canadabuys_ocds_pilot: a Phase 0 validation fixture, never
                # ingested into releases. A coverage row for it would misleadingly
                # read as a source that failed to load 0 records.
                continue
            count = connection.execute("SELECT COUNT(*) FROM releases WHERE source_id = ?", [config["source_id"]]).fetchone()[0]
            date_start, date_end = connection.execute(
                "SELECT MIN(TRY_CAST(json_extract_string(record, '$.date') AS TIMESTAMP)), "
                "MAX(TRY_CAST(json_extract_string(record, '$.date') AS TIMESTAMP)) "
                "FROM releases WHERE source_id = ?",
                [config["source_id"]],
            ).fetchone()
            known_gaps = config.get("known_gaps") or [config.get("notes", "")]
            connection.execute(
                "INSERT INTO coverage VALUES (?, ?, ?, ?, ?, ?, ?)",
                [config["source_id"], config["jurisdiction"], str(date_start) if date_start else None,
                 str(date_end) if date_end else None, config.get("value_threshold"), count, json.dumps(known_gaps)],
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--pairs", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    store = subparsers.add_parser("build-store")
    store.add_argument("--database", type=Path, required=True)
    store.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.command == "evaluate":
        print(json.dumps(evaluate_pairs(args.pairs, args.output), indent=2))
    else:
        build_entity_store(args.database, args.project_root)
        print("entity, entity_link, and coverage tables built")


if __name__ == "__main__":
    main()