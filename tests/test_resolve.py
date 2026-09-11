"""Tests for src/resolve.py: vendor normalization, blocking, and pair scoring."""

import csv

import pytest

from src.resolve import (
    LOWER_THRESHOLD,
    UPPER_THRESHOLD,
    block_key,
    classify_pair,
    evaluate_pairs,
    normalize_vendor,
    rank_candidates,
    score_names,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("IBM Canada Ltd.", "ibm canada"),
        ("IBM Canada Limited", "ibm canada"),
        ("Acme Consulting Inc.", "acme consulting"),
        ("ACME CONSULTING INC.", "acme consulting"),
        ("CompuStaff Inc", "compustaff"),
        ("CompuStaff Inc.", "compustaff"),
        ("Café Data Services Co.", "cafe data services"),
    ],
)
def test_normalize_vendor_strips_suffix_case_and_punctuation(raw, expected):
    assert normalize_vendor(raw) == expected


def test_normalize_vendor_is_idempotent_on_already_normalized_text():
    assert normalize_vendor("bell canada") == "bell canada"


def test_block_key_groups_numbered_companies_by_number():
    assert block_key("1234567 Ontario Inc.") == "numbered:1234567"
    assert block_key("1234567 Quebec Inc.") == "numbered:1234567"


def test_block_key_falls_back_to_first_token():
    assert block_key("Bell Canada") == "bell"


def test_block_key_empty_name():
    assert block_key("   ") == "empty"


def test_score_names_exact_normalized_match_is_100():
    assert score_names("CompuStaff Inc.", "CompuStaff Inc") == 100.0


def test_score_names_unrelated_names_score_low():
    assert score_names("Bell Canada", "1234567 Ontario Inc.") < LOWER_THRESHOLD


def test_classify_pair_auto_accepts_above_upper_threshold():
    result = classify_pair("Acme Consulting Inc.", "ACME CONSULTING INC.")
    assert result["decision"] is True
    assert result["score"] >= UPPER_THRESHOLD
    assert result["method"] in {"exact", "normalized"}


def test_classify_pair_auto_rejects_below_lower_threshold():
    result = classify_pair("Bell Canada", "The Ottawa Hospital")
    assert result["decision"] is False
    assert result["method"] == "fuzzy"
    assert result["score"] <= LOWER_THRESHOLD


def test_classify_pair_abstains_in_uncertain_band_without_adjudicator():
    result = classify_pair("Maple Leaf Data Services Ltd.", "Maple Leaf Data Solutions Ltd.")
    assert LOWER_THRESHOLD < result["score"] < UPPER_THRESHOLD
    assert result["method"] == "llm_adjudicated"
    assert result["decision"] is None


def test_classify_pair_uses_adjudicator_when_provided():
    result = classify_pair("Maple Leaf Data Services Ltd.", "Maple Leaf Data Solutions Ltd.", adjudicator=lambda a, b: True)
    assert result["decision"] is True
    assert result["method"] == "llm_adjudicated"


def test_classify_pair_evidence_carries_normalized_and_block_forms():
    result = classify_pair("IBM Canada Ltd.", "IBM Canada Limited")
    assert result["evidence"]["normalized_left"] == "ibm canada"
    assert result["evidence"]["normalized_right"] == "ibm canada"


def test_rank_candidates_only_returns_same_block():
    candidates = [
        {"source_vendor_name": "Bell Canada", "source_id": "a"},
        {"source_vendor_name": "IBM Canada Ltd.", "source_id": "b"},
    ]
    ranked = rank_candidates("Bell Canada Inc.", candidates)
    assert [c["source_vendor_name"] for c in ranked] == ["Bell Canada"]


def test_evaluate_pairs_reports_counts_by_jurisdiction_pair_and_marks_provisional(tmp_path):
    pairs_path = tmp_path / "pairs.csv"
    output_path = tmp_path / "out.log"
    with pairs_path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["pair_id", "source_a", "jurisdiction_a", "vendor_a", "source_b", "jurisdiction_b", "vendor_b", "label", "rationale"],
        )
        writer.writeheader()
        writer.writerow({"pair_id": "P1", "source_a": "federal_contracts", "jurisdiction_a": "federal", "vendor_a": "Bell Canada",
                          "source_b": "ontario_vor", "jurisdiction_b": "on", "vendor_b": "Bell Canada", "label": "match", "rationale": "exact"})
        writer.writerow({"pair_id": "P2", "source_a": "federal_contracts", "jurisdiction_a": "federal", "vendor_a": "Bell Canada",
                          "source_b": "ontario_vor", "jurisdiction_b": "on", "vendor_b": "The Ottawa Hospital", "label": "no-match", "rationale": "unrelated"})

    result = evaluate_pairs(pairs_path, output_path)

    assert result["evaluation"] == "PROVISIONAL"
    metrics = result["metrics_by_jurisdiction_pair"]["federal<->on"]
    assert metrics["tp"] == 1
    assert metrics["tn"] == 1
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert output_path.read_text().startswith("PROVISIONAL\n")
