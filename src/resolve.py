"""Deterministic vendor resolution, entity links, coverage, and evaluation."""

import argparse
import csv
import hashlib
import json
import re
import tempfile
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
# Auto-accept / auto-reject bars for similarity scores (0-100); the band
# between them abstains, or goes to an adjudicator when one is configured.
# Checked against real near-misses in this warehouse: "Dell Canada" vs
# "Bell Canada" (54.5) and "Acme Consulting" vs "Acme Consulting Group"
# (83.3) must not auto-accept, while "J.L. Richards Associates" vs "J.L.
# Richards and Associates" (92.0) and "Northstar Engineering Ltd." vs
# "North Star Engineering Limited" (97.7) should. 65 is the floor below
# which token overlap is too thin to mean anything ("Data Services" vs
# "Data Systems" scores 64).
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
    """Similarity of two vendor names after normalization, 0-100.

    Uses token_sort_ratio, not token_set_ratio. token_set_ratio compares
    the shared-token intersection against the union, so a name whose tokens
    are a strict subset of a longer one scores 100 regardless of meaning --
    at this warehouse's scale that produced ~4,000 bogus auto-accepts,
    including a 30-character firm name matching a 620-character multi-vendor
    roster at 100.0. token_sort_ratio compares the full sorted strings, so
    extra tokens on either side correctly cost score. See docs/FAILURES.md
    #17 and the ADR in docs/DECISIONS.md.
    """
    normalized_left, normalized_right = normalize_vendor(left), normalize_vendor(right)
    if normalized_left == normalized_right:
        return 100.0
    return float(fuzz.token_sort_ratio(normalized_left, normalized_right))


def classify_pair(left: str, right: str, adjudicator: Any = None) -> dict[str, Any]:
    score = score_names(left, right)
    if score >= UPPER_THRESHOLD:
        # "exact" only for true normalized equality; a high-but-imperfect
        # score is "normalized". The label should never claim more than the
        # match actually is.
        exact = normalize_vendor(left) == normalize_vendor(right)
        decision, method = True, "exact" if exact else "normalized"
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


def evaluate_pairs(pair_path: Path, output_path: Path) -> dict[str, Any]:
    with pair_path.open(newline="") as stream:
        rows: list[dict[str, str]] = list(csv.DictReader(stream))
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


# A token shared by more than this many entities (e.g. "canada", "services")
# discriminates nothing and only inflates the candidate-pair scan; it is
# dropped from the blocking index. Entities whose every token is this common
# simply generate no fuzzy candidates -- exact-normalized clustering still
# covers them.
BLOCKING_TOKEN_CAP = 200


def blocking_tokens(normalized: str) -> set[str]:
    """Tokens an entity is discoverable by in the blocking index. Numbered
    companies additionally index their numeric prefix as its own key
    (spec Part 8's numbered-company case)."""
    tokens = set(normalized.split())
    numbered = re.match(r"(\d+)", normalized)
    if numbered:
        tokens.add(f"numbered:{numbered.group(1)}")
    return tokens


def _bulk_insert(connection: duckdb.DuckDBPyConnection, table: str, rows: list[tuple[Any, ...]]) -> None:
    """Load rows by staging a CSV and letting DuckDB read it natively.

    DuckDB's executemany issues one prepared-statement round trip per row:
    ~23s per 70k rows, which at this store's row counts dominated the entire
    rebuild (minutes). Staging to a temp CSV and inserting via read_csv does
    the same work in ~0.06s -- a ~380x difference -- with no new dependency.
    Column types come from the table itself so JSON columns round-trip as
    the strings they already are.
    """
    if not rows:
        return
    schema = connection.execute(f"SELECT * FROM {table} LIMIT 0").description
    columns = "{" + ", ".join(f"'{name}': '{type_name}'" for name, type_name, *_ in schema) + "}"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", newline="", delete=False) as stream:
        csv.writer(stream).writerows(rows)
        staged = stream.name
    try:
        connection.execute(
            f"INSERT INTO {table} SELECT * FROM read_csv(?, header=false, columns={columns})",
            [staged],
        )
    finally:
        Path(staged).unlink(missing_ok=True)


def _collect_vendor_occurrences(connection: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[str, str]]]:
    """Every (source_id, verbatim vendor name) occurrence across all releases,
    grouped by normalized name -- one group becomes one resolved entity.

    Rows flagged `_provenance.multi_vendor_row` are skipped: their vendor
    field is a roster of firms, not one entity, so resolving it as a single
    vendor would assert a company that doesn't exist. The release itself
    stays in the warehouse (see src/extract_documents.py)."""
    vendors: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for source_id, raw_record in connection.execute("SELECT source_id, record FROM releases").fetchall():
        record = json.loads(raw_record)
        if (record.get("_provenance") or {}).get("multi_vendor_row"):
            continue
        for award in record.get("awards", []):
            for supplier in award.get("suppliers", []):
                name = supplier.get("name", "")
                if name:
                    vendors[normalize_vendor(name)].append((source_id, name))
    return vendors


def _reset_resolution_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("DROP TABLE IF EXISTS entity_token")
    connection.execute("DROP TABLE IF EXISTS entity_link")
    connection.execute("DROP TABLE IF EXISTS entity")
    connection.execute("DROP TABLE IF EXISTS coverage")
    connection.execute("CREATE TABLE entity (entity_id VARCHAR, canonical_name VARCHAR, name_variants JSON, registry_id VARCHAR, resolution_mode VARCHAR)")
    connection.execute("CREATE TABLE entity_link (entity_id VARCHAR, source_id VARCHAR, source_vendor_name VARCHAR, confidence DOUBLE, method VARCHAR, evidence JSON)")
    connection.execute("CREATE TABLE entity_token (token VARCHAR, entity_id VARCHAR)")
    connection.execute("CREATE TABLE coverage (source_id VARCHAR, jurisdiction VARCHAR, date_range_start VARCHAR, date_range_end VARCHAR, value_threshold DOUBLE, record_count INTEGER, known_gaps JSON)")


def _write_entities_and_links(connection: duckdb.DuckDBPyConnection, vendors: dict[str, list[tuple[str, str]]]) -> None:
    """One entity per normalized-name group; one entity_link row per
    (source, verbatim name) occurrence, all at confidence 1.0/"normalized" --
    this is exact-normalized clustering only. Fuzzy/uncertain-band candidates
    are scored live at query time by agent_tools.resolve_vendor, not
    persisted here."""
    entity_rows: list[tuple[str, str, str, None, str]] = []
    link_rows: list[tuple[str, str, str, float, str, str]] = []
    for normalized, links in vendors.items():
        entity_id = _entity_id(normalized)
        variants = sorted({name for _, name in links})
        entity_rows.append((entity_id, links[0][1], json.dumps(variants), None, "vendor_to_vendor"))
        evidence = json.dumps({"normalized_name": normalized, "blocking": "exact_normalized"})
        link_rows.extend(
            (entity_id, source_id, name, 1.0, "normalized", evidence) for source_id, name in links
        )
    _bulk_insert(connection, "entity", entity_rows)
    _bulk_insert(connection, "entity_link", link_rows)


def _write_blocking_index(connection: duckdb.DuckDBPyConnection, vendors: dict[str, list[tuple[str, str]]]) -> dict[str, list[str]]:
    """Persist the token blocking index (entity_token) and return the
    surviving token -> entity_ids buckets for the cross-entity scan."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for normalized in vendors:
        entity_id = _entity_id(normalized)
        for token in blocking_tokens(normalized):
            buckets[token].append(entity_id)
    buckets = {token: ids for token, ids in buckets.items() if len(ids) <= BLOCKING_TOKEN_CAP}
    _bulk_insert(
        connection, "entity_token",
        [(token, entity_id) for token, ids in buckets.items() for entity_id in ids],
    )
    return buckets


def _write_cross_entity_links(
    connection: duckdb.DuckDBPyConnection,
    vendors: dict[str, list[tuple[str, str]]],
    buckets: dict[str, list[str]],
) -> None:
    """Score every entity pair sharing a blocking token and persist both
    bands (spec Part 8: block -> score -> band -> link, never merge):

    - score >= UPPER_THRESHOLD: an asserted cross-entity link, method
      "normalized", at its real confidence (score/100). This is where the
      known token-superset auto-accepts land (FAILURES.md #17) -- linked
      with their evidence visible, not silently merged.
    - LOWER < score < UPPER: an unadjudicated candidate, method "fuzzy",
      decision explicitly absent. Persisted so the uncertain band is
      durable and queryable, but excluded from profile aggregation and
      site counts until adjudicated (see agent_tools / docs/DECISIONS.md).
    """
    normalized_by_id = {_entity_id(normalized): normalized for normalized in vendors}
    names_by_id = {
        _entity_id(normalized): sorted({(source_id, name) for source_id, name in links})
        for normalized, links in vendors.items()
    }
    rows: list[tuple[str, str, str, float, str, str]] = []
    seen: set[frozenset[str]] = set()
    for token, ids in buckets.items():
        for index, left_id in enumerate(ids):
            for right_id in ids[index + 1:]:
                pair = frozenset((left_id, right_id))
                if pair in seen:
                    continue
                seen.add(pair)
                score = score_names(normalized_by_id[left_id], normalized_by_id[right_id])
                if score <= LOWER_THRESHOLD:
                    continue
                if score >= UPPER_THRESHOLD:
                    method, band = "normalized", "auto_accept"
                else:
                    method, band = "fuzzy", "uncertain_unadjudicated"
                confidence = round(score / 100, 3)
                for target_id, other_id in ((left_id, right_id), (right_id, left_id)):
                    evidence = json.dumps({
                        "blocking": "token", "token": token, "score": round(score, 3), "band": band,
                        "matched_entity": other_id, "matched_normalized": normalized_by_id[other_id],
                    })
                    rows.extend(
                        (target_id, source_id, name, confidence, method, evidence)
                        for source_id, name in names_by_id[other_id]
                    )
    _bulk_insert(connection, "entity_link", rows)


def _write_coverage(connection: duckdb.DuckDBPyConnection, project_root: Path) -> None:
    for source_file in sorted((project_root / "sources").glob("*/source.yaml")):
        config = yaml.safe_load(source_file.read_text())
        if config.get("role") == "schema_ground_truth":
            # e.g. canadabuys_ocds_pilot: a Phase 0 validation fixture, never
            # ingested into releases. A coverage row for it would misleadingly
            # read as a source that failed to load 0 records.
            continue
        count = connection.execute("SELECT COUNT(*) FROM releases WHERE source_id = ?", [config["source_id"]]).fetchone()[0]
        # Document-extracted records (both Ottawa sources) store the report's
        # period END as their `date` because no per-row award date is
        # published -- so the range start must also consider the extracted
        # report_period_start, or a Jan-Jun report reads as starting in June
        # and the coverage table implies a gap that doesn't exist. Sources
        # without that provenance field are unaffected (the MIN is NULL).
        min_date, date_end, min_period_start = connection.execute(
            "SELECT MIN(TRY_CAST(json_extract_string(record, '$.date') AS TIMESTAMP)), "
            "MAX(TRY_CAST(json_extract_string(record, '$.date') AS TIMESTAMP)), "
            "MIN(TRY_CAST(json_extract_string(record, '$._provenance.report_period_start') AS TIMESTAMP)) "
            "FROM releases WHERE source_id = ?",
            [config["source_id"]],
        ).fetchone()
        start_candidates = [d for d in (min_date, min_period_start) if d is not None]
        date_start = min(start_candidates) if start_candidates else None
        known_gaps = config.get("known_gaps") or [config.get("notes", "")]
        connection.execute(
            "INSERT INTO coverage VALUES (?, ?, ?, ?, ?, ?, ?)",
            [config["source_id"], config["jurisdiction"], str(date_start) if date_start else None,
             str(date_end) if date_end else None, config.get("value_threshold"), count, json.dumps(known_gaps)],
        )


def build_entity_store(database: Path, project_root: Path) -> None:
    with duckdb.connect(str(database)) as connection:
        vendors = _collect_vendor_occurrences(connection)
        _reset_resolution_tables(connection)
        _write_entities_and_links(connection, vendors)
        buckets = _write_blocking_index(connection, vendors)
        _write_cross_entity_links(connection, vendors, buckets)
        _write_coverage(connection, project_root)


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