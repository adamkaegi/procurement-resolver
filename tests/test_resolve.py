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


def test_classify_pair_labels_true_normalized_equality_as_exact():
    result = classify_pair("Bell Canada", "BELL CANADA")
    assert result["decision"] is True
    assert result["method"] == "exact"


def test_token_superset_is_rejected_not_matched():
    # Regression pin for docs/FAILURES.md #17. Under token_set_ratio this
    # pair scored 100.0 and auto-accepted, because one name's tokens are a
    # strict subset of the other's. token_sort_ratio compares full sorted
    # strings, so the extra token costs score and the pair is rejected.
    result = classify_pair("Bell", "Bell Canada")
    assert result["score"] < LOWER_THRESHOLD
    assert result["decision"] is False


def test_extra_legal_name_token_does_not_auto_accept():
    # evals/provisional/resolution/pairs.csv P015 labels this no-match.
    # token_set_ratio scored it 100.0 (a false positive counted in the
    # provisional metrics); it must now land in the band, not auto-accept.
    result = classify_pair("Acme Consulting Inc.", "Acme Consulting Group Inc.")
    assert LOWER_THRESHOLD < result["score"] < UPPER_THRESHOLD
    assert result["decision"] is None


def test_dell_canada_vs_bell_canada_is_rejected():
    # One-character-different false friend: must never auto-accept.
    result = classify_pair("Dell Canada Inc.", "Bell Canada")
    assert result["score"] < UPPER_THRESHOLD
    assert result["decision"] is not True


def test_real_legal_name_variation_still_auto_accepts():
    # The matches the fuzzy band exists to catch (observed in the warehouse).
    for left, right in [
        ("Northstar Engineering Ltd.", "North Star Engineering Limited"),
        ("J.L. Richards & Associates Limited", "J L Richards and Associates"),
        ("GUILLEVIN INTERNATIONAL CO.", "Guillevin International"),
    ]:
        result = classify_pair(left, right)
        assert result["decision"] is True, f"{left} vs {right} -> {result['score']}"
        assert result["score"] >= UPPER_THRESHOLD


def test_build_entity_store_persists_both_bands_and_the_blocking_index(tmp_path):
    import duckdb

    from src.resolve import build_entity_store

    db_path = tmp_path / "store.duckdb"
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()

    def release(source_id, ocid, vendor):
        import json
        return (source_id, ocid, json.dumps({
            "ocid": ocid, "awards": [{"suppliers": [{"name": vendor}]}],
        }))

    with duckdb.connect(str(db_path)) as connection:
        connection.execute("CREATE TABLE releases (source_id VARCHAR, ocid VARCHAR, record JSON)")
        connection.executemany("INSERT INTO releases VALUES (?, ?, ?)", [
            # legal-name variation: auto-accepts as an asserted cross-entity link
            release("federal_contracts", "F1", "J.L. Richards & Associates Limited"),
            release("canadabuys_award_notices", "C1", "J L Richards and Associates"),
            # one altered token: lands in the uncertain band as a candidate
            release("federal_contracts", "F2", "Maple Leaf Data Services Ltd."),
            release("ontario_vor", "O1", "Maple Leaf Data Solutions Ltd."),
        ])

    build_entity_store(db_path, tmp_path)

    with duckdb.connect(str(db_path), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM entity").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM entity_token").fetchone()[0] > 0

        asserted_cross = connection.execute(
            "SELECT source_vendor_name, confidence FROM entity_link "
            "WHERE method = 'normalized' AND json_extract_string(evidence, '$.blocking') = 'token'"
        ).fetchall()
        # The J.L. Richards legal-name variation links across sources, both ways.
        assert {name for name, _ in asserted_cross} == {
            "J.L. Richards & Associates Limited", "J L Richards and Associates",
        }
        assert all(confidence >= 0.92 for _, confidence in asserted_cross)

        candidates = connection.execute(
            "SELECT source_vendor_name, confidence FROM entity_link WHERE method = 'fuzzy'"
        ).fetchall()
        # the Maple Leaf pair lands in the uncertain band, persisted as
        # candidates with their real (sub-floor) confidence, decision absent.
        assert {name for name, _ in candidates} == {"Maple Leaf Data Services Ltd.", "Maple Leaf Data Solutions Ltd."}
        assert all(0.65 < confidence < 0.92 for _, confidence in candidates)


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
