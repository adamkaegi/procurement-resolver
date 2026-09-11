"""Tests for src/agent_tools.py: the five typed MCP tools, especially refusal
logic. Builds a small synthetic warehouse rather than depending on the real
data/warehouse.duckdb, so these run anywhere with no fixture data required.
"""

import json

import duckdb
import pytest

from src.agent_tools import (
    compare_buyers,
    coverage,
    cross_level_exposure,
    entity_profile,
    resolve_vendor,
)


def _release(source_id, ocid, buyer_name, vendor_name, amount, date="2024-01-01T00:00:00+00:00", description="test award"):
    return (
        source_id,
        ocid,
        json.dumps({
            "ocid": ocid,
            "id": ocid,
            "date": date,
            "buyer": {"name": buyer_name},
            "awards": [{
                "id": ocid,
                "date": date,
                "value": {"amount": amount, "currency": "CAD"},
                "suppliers": [{"name": vendor_name}],
                "description": description,
            }],
        }),
    )


@pytest.fixture
def warehouse(tmp_path):
    db_path = tmp_path / "test.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute("CREATE TABLE releases (source_id VARCHAR, ocid VARCHAR, record JSON)")
    connection.execute("CREATE TABLE entity (entity_id VARCHAR, canonical_name VARCHAR, name_variants JSON, registry_id VARCHAR, resolution_mode VARCHAR)")
    connection.execute("CREATE TABLE entity_link (entity_id VARCHAR, source_id VARCHAR, source_vendor_name VARCHAR, confidence DOUBLE, method VARCHAR, evidence JSON)")
    connection.execute("CREATE TABLE coverage (source_id VARCHAR, jurisdiction VARCHAR, date_range_start VARCHAR, date_range_end VARCHAR, value_threshold DOUBLE, record_count INTEGER, known_gaps JSON)")

    releases = [
        _release("federal_contracts", "F1", "Dept of Fictional Affairs", "Bell Canada", 50000.0),
        _release("federal_contracts", "F2", "Dept of Fictional Affairs", "Bell Canada", 25000.0),
        _release("ontario_vor", "O1", "Ontario Government", "Bell Canada", 0.0),
        _release("federal_contracts", "F3", "Dept of Fictional Affairs", "Sole Federal Vendor Inc.", 10000.0),
    ]
    connection.executemany("INSERT INTO releases VALUES (?, ?, ?)", releases)

    # "Bell Canada" entity: linked in both federal_contracts and ontario_vor.
    connection.execute("INSERT INTO entity VALUES ('ent_bell', 'Bell Canada', ?, NULL, 'vendor_to_vendor')", [json.dumps(["Bell Canada"])])
    connection.executemany(
        "INSERT INTO entity_link VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("ent_bell", "federal_contracts", "Bell Canada", 1.0, "normalized", json.dumps({})),
            ("ent_bell", "federal_contracts", "Bell Canada", 1.0, "normalized", json.dumps({})),
            ("ent_bell", "ontario_vor", "Bell Canada", 1.0, "normalized", json.dumps({})),
        ],
    )
    # single-jurisdiction entity: only ever appears federally.
    connection.execute("INSERT INTO entity VALUES ('ent_solo', 'Sole Federal Vendor Inc.', ?, NULL, 'vendor_to_vendor')", [json.dumps(["Sole Federal Vendor Inc."])])
    connection.execute(
        "INSERT INTO entity_link VALUES ('ent_solo', 'federal_contracts', 'Sole Federal Vendor Inc.', 1.0, 'normalized', ?)",
        [json.dumps({})],
    )

    connection.execute(
        "INSERT INTO coverage VALUES ('federal_contracts', 'federal', '2020-01-01', '2024-12-31', 10000.0, 3, ?)",
        [json.dumps(["Federal proactive disclosure covers contracts over $10,000."])],
    )
    connection.execute(
        "INSERT INTO coverage VALUES ('ontario_vor', 'on', '2020-01-01', '2024-12-31', 25000.0, 1, ?)",
        [json.dumps(["Award value is unmapped and deterministically zero."])],
    )
    yield connection
    connection.close()


def test_resolve_vendor_ranks_exact_match_highest(warehouse):
    result = resolve_vendor(warehouse, "Bell Canada")
    assert result.candidates
    assert result.candidates[0].canonical_name == "Bell Canada"
    assert result.candidates[0].confidence == 1.0


def test_resolve_vendor_respects_jurisdiction_filter(warehouse):
    result = resolve_vendor(warehouse, "Bell Canada", jurisdiction="on")
    assert all(c.matched_source_id == "ontario_vor" for c in result.candidates if c.canonical_name == "Bell Canada")


def test_entity_profile_gathers_contracts_across_sources(warehouse):
    profile = entity_profile(warehouse, "ent_bell")
    assert profile is not None
    assert profile.jurisdictions_present == ["federal", "on"]
    assert len(profile.contracts) == 3  # F1, F2, O1


def test_entity_profile_unknown_entity_returns_none(warehouse):
    assert entity_profile(warehouse, "ent_does_not_exist") is None


def test_cross_level_exposure_aggregates_and_excludes_zero_value_source(warehouse):
    result = cross_level_exposure(warehouse, "ent_bell")
    assert result is not None
    assert result.declined is False
    by_jurisdiction = {e.jurisdiction: e for e in result.exposures}
    assert by_jurisdiction["federal"].total_amount == 75000.0
    assert by_jurisdiction["on"].total_amount is None
    assert by_jurisdiction["on"].amount_caveat is not None


def test_cross_level_exposure_declines_for_single_jurisdiction_entity(warehouse):
    result = cross_level_exposure(warehouse, "ent_solo")
    assert result is not None
    assert result.declined is True
    assert "only 1 jurisdiction" in result.decline_reason


def test_compare_buyers_flags_different_thresholds(warehouse):
    result = compare_buyers(warehouse, jurisdictions=["federal", "on"])
    assert any("different disclosure thresholds" in c for c in result.caveats)


def test_compare_buyers_reports_total_at_the_sample_floor(warehouse):
    result = compare_buyers(warehouse, jurisdictions=["federal"])
    buyer = next(r for r in result.results if r.buyer_name == "Dept of Fictional Affairs")
    # exactly 3 federal records for this buyer -- at the floor, not below it -- so it reports.
    assert buyer.contract_count == 3
    assert buyer.declined is False
    assert buyer.total_amount == 85000.0


def test_compare_buyers_declines_below_sample_floor(warehouse):
    result = compare_buyers(warehouse, jurisdictions=["on"])
    buyer = next(r for r in result.results if r.buyer_name == "Ontario Government")
    # only 1 ontario_vor record -- below the 3-record floor -- must decline rather than report a total.
    assert buyer.declined is True
    assert buyer.total_amount is None
    assert "1 matching record" in buyer.decline_reason


def test_coverage_filters_by_jurisdiction(warehouse):
    result = coverage(warehouse, jurisdiction="federal")
    assert len(result.entries) == 1
    assert result.entries[0].source_id == "federal_contracts"
    assert result.entries[0].value_threshold == 10000.0


def test_coverage_flags_out_of_range_request(warehouse):
    result = coverage(warehouse, jurisdiction="federal", date_start="2030-01-01")
    assert any("before the requested start" in c for c in result.caveats)


def test_coverage_no_filter_returns_all_sources(warehouse):
    result = coverage(warehouse)
    assert {e.source_id for e in result.entries} == {"federal_contracts", "ontario_vor"}
