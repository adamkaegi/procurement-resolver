"""Typed, deterministic implementations of the five agent tools (spec Part 9).

Every function here takes a read-only DuckDB connection and returns a
pydantic model -- no free-text SQL is ever accepted from a caller (no
run_sql, per CLAUDE.md rule 5 / spec Part 9). src/server.py wires these as
MCP tools; this module has no MCP dependency so it's testable on its own.

Refusal logic lives here, not in the LLM: cross_level_exposure and
compare_buyers decline to aggregate rather than silently blending
differently-censored jurisdictions or low-confidence entity links.
"""

import json
from typing import Any

import duckdb
from pydantic import BaseModel

from .resolve import UPPER_THRESHOLD, classify_pair, score_names

# Same auto-accept bar entity resolution already uses (resolve.UPPER_THRESHOLD
# is a 0-100 score; aggregation confidence here is 0-1). Reusing it rather
# than inventing a second number to tune -- see docs/DECISIONS.md.
AGGREGATION_CONFIDENCE_FLOOR = UPPER_THRESHOLD / 100
MIN_BUYER_AGGREGATE_SAMPLE = 3


# --- models -----------------------------------------------------------------


class EntityCandidate(BaseModel):
    entity_id: str
    canonical_name: str
    matched_source_id: str
    matched_source_vendor_name: str
    confidence: float
    method: str


class ResolveVendorResult(BaseModel):
    query: str
    jurisdiction_filter: str | None
    candidates: list[EntityCandidate]


class ContractSummary(BaseModel):
    source_id: str
    jurisdiction: str | None
    ocid: str
    award_id: str
    date: str | None
    amount: float
    currency: str
    buyer_name: str | None
    description: str | None


class EntityLinkSummary(BaseModel):
    source_id: str
    source_vendor_name: str
    confidence: float
    method: str


class EntityProfileResult(BaseModel):
    entity_id: str
    canonical_name: str
    name_variants: list[str]
    links: list[EntityLinkSummary]
    contracts: list[ContractSummary]
    jurisdictions_present: list[str]


class JurisdictionExposure(BaseModel):
    jurisdiction: str
    source_id: str
    contract_count: int
    total_amount: float | None
    amount_caveat: str | None
    value_threshold: float | None
    known_gaps: list[str]


class CrossLevelExposureResult(BaseModel):
    entity_id: str
    canonical_name: str
    declined: bool
    decline_reason: str | None
    overall_confidence: float | None
    exposures: list[JurisdictionExposure]


class BuyerAggregate(BaseModel):
    jurisdiction: str
    buyer_name: str
    contract_count: int
    total_amount: float | None
    declined: bool
    decline_reason: str | None


class CompareBuyersResult(BaseModel):
    jurisdictions: list[str]
    category_filter: str | None
    results: list[BuyerAggregate]
    caveats: list[str]


class CoverageEntry(BaseModel):
    source_id: str
    jurisdiction: str
    date_range_start: str | None
    date_range_end: str | None
    value_threshold: float | None
    record_count: int
    known_gaps: list[str]


class CoverageResult(BaseModel):
    entries: list[CoverageEntry]
    requested_jurisdiction: str | None
    requested_date_range: list[str | None] | None
    caveats: list[str]


# --- shared helpers -----------------------------------------------------------


def _award(record: dict[str, Any]) -> dict[str, Any]:
    awards = record.get("awards") or [{}]
    return awards[0]


def _coverage_rows(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT source_id, jurisdiction, date_range_start, date_range_end, "
        "value_threshold, record_count, known_gaps FROM coverage"
    ).fetchall()
    columns = ["source_id", "jurisdiction", "date_range_start", "date_range_end", "value_threshold", "record_count", "known_gaps"]
    return [dict(zip(columns, row)) for row in rows]


def source_jurisdiction_map(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return {row["source_id"]: row["jurisdiction"] for row in _coverage_rows(connection)}


# --- tool 1: resolve_vendor ---------------------------------------------------


def resolve_vendor(connection: duckdb.DuckDBPyConnection, name: str, jurisdiction: str | None = None, limit: int = 10) -> ResolveVendorResult:
    jurisdiction_map = source_jurisdiction_map(connection)
    entities = connection.execute("SELECT entity_id, canonical_name, name_variants FROM entity").fetchall()

    candidates: list[EntityCandidate] = []
    for entity_id, canonical_name, variants_json in entities:
        variants = json.loads(variants_json) or [canonical_name]
        best_variant, best_score = None, -1.0
        for variant in variants:
            score = score_names(name, variant)
            if score > best_score:
                best_variant, best_score = variant, score
        result = classify_pair(name, best_variant)
        links = connection.execute(
            "SELECT source_id, source_vendor_name FROM entity_link WHERE entity_id = ? AND source_vendor_name = ? LIMIT 1",
            [entity_id, best_variant],
        ).fetchone()
        if links is None:
            continue
        source_id, matched_name = links
        if jurisdiction and jurisdiction_map.get(source_id) != jurisdiction:
            continue
        candidates.append(EntityCandidate(
            entity_id=entity_id,
            canonical_name=canonical_name,
            matched_source_id=source_id,
            matched_source_vendor_name=matched_name,
            confidence=round(result["confidence"], 3),
            method=result["method"] if result["method"] != "llm_adjudicated" else "fuzzy_unadjudicated",
        ))

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return ResolveVendorResult(query=name, jurisdiction_filter=jurisdiction, candidates=candidates[:limit])


# --- tool 2: entity_profile ----------------------------------------------------


def _entity_links(connection: duckdb.DuckDBPyConnection, entity_id: str) -> list[EntityLinkSummary]:
    rows = connection.execute(
        "SELECT DISTINCT source_id, source_vendor_name, confidence, method FROM entity_link WHERE entity_id = ?",
        [entity_id],
    ).fetchall()
    return [EntityLinkSummary(source_id=r[0], source_vendor_name=r[1], confidence=r[2], method=r[3]) for r in rows]


def _contracts_for_links(connection: duckdb.DuckDBPyConnection, links: list[EntityLinkSummary]) -> list[ContractSummary]:
    jurisdiction_map = source_jurisdiction_map(connection)
    contracts: list[ContractSummary] = []
    for link in links:
        rows = connection.execute(
            "SELECT record FROM releases WHERE source_id = ? "
            "AND json_extract_string(record, '$.awards[0].suppliers[0].name') = ?",
            [link.source_id, link.source_vendor_name],
        ).fetchall()
        for (raw,) in rows:
            record = json.loads(raw)
            award = _award(record)
            value = award.get("value") or {}
            contracts.append(ContractSummary(
                source_id=link.source_id,
                jurisdiction=jurisdiction_map.get(link.source_id),
                ocid=record.get("ocid", ""),
                award_id=award.get("id", ""),
                date=record.get("date"),
                amount=float(value.get("amount") or 0.0),
                currency=value.get("currency") or "CAD",
                buyer_name=(record.get("buyer") or {}).get("name"),
                description=award.get("description"),
            ))
    return contracts


def entity_profile(connection: duckdb.DuckDBPyConnection, entity_id: str) -> EntityProfileResult | None:
    row = connection.execute("SELECT canonical_name, name_variants FROM entity WHERE entity_id = ?", [entity_id]).fetchone()
    if row is None:
        return None
    canonical_name, variants_json = row
    links = _entity_links(connection, entity_id)
    contracts = _contracts_for_links(connection, links)
    jurisdictions = sorted({c.jurisdiction for c in contracts if c.jurisdiction})
    return EntityProfileResult(
        entity_id=entity_id,
        canonical_name=canonical_name,
        name_variants=json.loads(variants_json),
        links=links,
        contracts=contracts,
        jurisdictions_present=jurisdictions,
    )


# --- tool 3: cross_level_exposure ----------------------------------------------


def cross_level_exposure(connection: duckdb.DuckDBPyConnection, entity_id: str) -> CrossLevelExposureResult | None:
    profile = entity_profile(connection, entity_id)
    if profile is None:
        return None

    coverage_by_source = {row["source_id"]: row for row in _coverage_rows(connection)}
    overall_confidence = min((link.confidence for link in profile.links), default=None)

    exposures: list[JurisdictionExposure] = []
    for source_id in sorted({c.source_id for c in profile.contracts}):
        source_contracts = [c for c in profile.contracts if c.source_id == source_id]
        coverage_row = coverage_by_source.get(source_id, {})
        amounts = [c.amount for c in source_contracts]
        all_zero = bool(amounts) and all(a == 0.0 for a in amounts)
        exposures.append(JurisdictionExposure(
            jurisdiction=coverage_row.get("jurisdiction", source_contracts[0].jurisdiction or "unknown"),
            source_id=source_id,
            contract_count=len(source_contracts),
            total_amount=None if all_zero else round(sum(amounts), 2),
            amount_caveat=(
                f"All {len(amounts)} included contract(s) from {source_id} show $0. This may be the "
                "source's design (e.g. Ontario VOR publishes no per-transaction value at all) or a "
                "data-quality artifact in this specific slice (e.g. an unpriced standing offer or a "
                "blank source field) -- it is not confirmed zero spend either way. Excluded from the "
                "dollar total rather than silently included as $0." if all_zero else None
            ),
            value_threshold=coverage_row.get("value_threshold"),
            known_gaps=json.loads(coverage_row["known_gaps"]) if coverage_row.get("known_gaps") else [],
        ))

    jurisdictions_represented = {e.jurisdiction for e in exposures}
    declined, decline_reason = False, None
    if len(jurisdictions_represented) < 2:
        declined = True
        decline_reason = (
            f"This entity currently resolves to records in only {len(jurisdictions_represented)} "
            "jurisdiction(s). Cross-level exposure requires more than one to be meaningful; "
            "returning per-source detail instead of a cross-level total."
        )
    elif overall_confidence is not None and overall_confidence < AGGREGATION_CONFIDENCE_FLOOR:
        declined = True
        decline_reason = (
            f"Weakest entity link confidence is {overall_confidence:.2f}, below the "
            f"{AGGREGATION_CONFIDENCE_FLOOR:.2f} floor used for cross-level aggregation. "
            "Returning per-source detail instead of a combined total."
        )

    return CrossLevelExposureResult(
        entity_id=entity_id,
        canonical_name=profile.canonical_name,
        declined=declined,
        decline_reason=decline_reason,
        overall_confidence=overall_confidence,
        exposures=exposures,
    )


# --- tool 4: compare_buyers -----------------------------------------------------


def compare_buyers(connection: duckdb.DuckDBPyConnection, jurisdictions: list[str], category: str | None = None, limit: int = 10) -> CompareBuyersResult:
    coverage_rows = [row for row in _coverage_rows(connection) if row["jurisdiction"] in jurisdictions]
    caveats: list[str] = []

    thresholds = {row["value_threshold"] for row in coverage_rows if row["value_threshold"] is not None}
    if len(thresholds) > 1:
        caveats.append(
            f"Compared jurisdictions use different disclosure thresholds ({sorted(thresholds)}); "
            "these are differently-censored populations, not a like-for-like comparison."
        )
    for row in coverage_rows:
        for gap in json.loads(row["known_gaps"]) if row["known_gaps"] else []:
            if gap:
                caveats.append(f"[{row['source_id']}] {gap}")

    results: list[BuyerAggregate] = []
    for row in coverage_rows:
        source_id, jurisdiction = row["source_id"], row["jurisdiction"]
        raw_rows = connection.execute("SELECT record FROM releases WHERE source_id = ?", [source_id]).fetchall()
        buyer_totals: dict[str, list[float]] = {}
        for (raw,) in raw_rows:
            record = json.loads(raw)
            award = _award(record)
            if category and category.lower() not in (award.get("description") or "").lower():
                continue
            buyer_name = (record.get("buyer") or {}).get("name") or "Unknown"
            buyer_totals.setdefault(buyer_name, []).append(float((award.get("value") or {}).get("amount") or 0.0))

        ranked_buyers = sorted(buyer_totals.items(), key=lambda item: sum(item[1]), reverse=True)[:limit]
        for buyer_name, amounts in ranked_buyers:
            all_zero = all(a == 0.0 for a in amounts)
            insufficient = len(amounts) < MIN_BUYER_AGGREGATE_SAMPLE
            results.append(BuyerAggregate(
                jurisdiction=jurisdiction,
                buyer_name=buyer_name,
                contract_count=len(amounts),
                total_amount=None if (all_zero or insufficient) else round(sum(amounts), 2),
                declined=insufficient,
                decline_reason=(
                    f"Only {len(amounts)} matching record(s), below the {MIN_BUYER_AGGREGATE_SAMPLE}-record "
                    "floor for reporting an aggregate; returning the count only." if insufficient else
                    (f"All {len(amounts)} matching record(s) show $0 (source design or a data-quality "
                     "artifact -- not confirmed zero spend); excluded rather than reported as $0." if all_zero else None)
                ),
            ))

    return CompareBuyersResult(jurisdictions=jurisdictions, category_filter=category, results=results, caveats=caveats)


# --- tool 5: coverage ------------------------------------------------------------


def coverage(connection: duckdb.DuckDBPyConnection, jurisdiction: str | None = None, date_start: str | None = None, date_end: str | None = None) -> CoverageResult:
    rows = _coverage_rows(connection)
    if jurisdiction:
        rows = [row for row in rows if row["jurisdiction"] == jurisdiction]

    caveats: list[str] = []
    entries: list[CoverageEntry] = []
    for row in rows:
        if date_start and row["date_range_end"] and str(row["date_range_end"]) < date_start:
            caveats.append(f"{row['source_id']}: archived data ends {row['date_range_end']}, before the requested start {date_start}.")
        if date_end and row["date_range_start"] and str(row["date_range_start"]) > date_end:
            caveats.append(f"{row['source_id']}: archived data starts {row['date_range_start']}, after the requested end {date_end}.")
        entries.append(CoverageEntry(
            source_id=row["source_id"],
            jurisdiction=row["jurisdiction"],
            date_range_start=str(row["date_range_start"]) if row["date_range_start"] else None,
            date_range_end=str(row["date_range_end"]) if row["date_range_end"] else None,
            value_threshold=row["value_threshold"],
            record_count=row["record_count"],
            known_gaps=json.loads(row["known_gaps"]) if row["known_gaps"] else [],
        ))

    return CoverageResult(
        entries=entries,
        requested_jurisdiction=jurisdiction,
        requested_date_range=[date_start, date_end] if (date_start or date_end) else None,
        caveats=caveats,
    )
