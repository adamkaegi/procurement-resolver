"""Tests for src/apply_mapping.py: deterministic Phase 1 mapping application.

Uses the real, committed sources/*/mapping.yaml configs against small
synthetic fixture CSVs shaped like the archived raw headers, so a change to
either the mapping config or the applier is caught here without touching
data/raw/.
"""

from pathlib import Path

import pytest

from src.apply_mapping import ingest_csv

ROOT = Path(__file__).resolve().parents[1]


def test_federal_contracts_maps_core_fields(tmp_path):
    csv_path = tmp_path / "contracts.csv"
    csv_path.write_text(
        "reference_number,procurement_id,vendor_name,buyer_name,contract_date,"
        "description_en,contract_period_start,delivery_date,contract_value,commodity_code\n"
        "REF-1,PROC-1,Bell Canada,Department of Fictional Affairs,2024-01-15,"
        "Telecom services,2024-01-01,2024-12-31,50000,UNSPSC123\n"
    )
    releases = ingest_csv(csv_path, ROOT / "sources/federal_contracts/mapping.yaml")

    assert len(releases) == 1
    release = releases[0]
    assert release["ocid"] == "PROC-1"
    assert release["id"] == "REF-1"
    assert release["buyer"]["name"] == "Department of Fictional Affairs"
    assert release["buyer"]["jurisdiction"] == "federal"
    assert release["awards"][0]["suppliers"][0]["name"] == "Bell Canada"
    assert release["awards"][0]["value"]["amount"] == 50000.0
    assert release["_provenance"]["source_id"] == "federal_contracts"
    assert release["_provenance"]["raw_ref"] == str(csv_path)


def test_federal_contracts_amount_strips_currency_formatting(tmp_path):
    csv_path = tmp_path / "contracts.csv"
    csv_path.write_text(
        "reference_number,procurement_id,vendor_name,buyer_name,contract_date,"
        "description_en,contract_period_start,delivery_date,contract_value,commodity_code\n"
        'REF-1,PROC-1,Vendor A,Buyer A,2024-01-15,desc,2024-01-01,2024-12-31,"$1,234,567.89",X\n'
    )
    releases = ingest_csv(csv_path, ROOT / "sources/federal_contracts/mapping.yaml")
    assert releases[0]["awards"][0]["value"]["amount"] == pytest.approx(1234567.89)


def test_canadabuys_negative_contract_amount_falls_back_to_total_value(tmp_path):
    csv_path = tmp_path / "awards.csv"
    header = (
        "solicitationNumber-numeroSollicitation,referenceNumber-numeroReference,contractNumber-numeroContrat,"
        "contractAwardDate-dateAttributionContrat,publicationDate-datePublication,"
        "contractingEntityName-nomEntitContractante-eng,supplierLegalName-nomLegalFournisseur-eng,"
        "contractAmount-montantContrat,totalContractValue-valeurTotaleContrat,"
        "awardDescription-descriptionAttribution-eng,title-titre-eng,unspsc-unspsc,gsin-nibs,"
        "contractStartDate-contratDateDebut,contractEndDate-dateFinContrat,contractCurrency-contratMonnaie\n"
    )
    row = "SOL-1,REF-1,CON-1,2024-02-01,2024-01-01,Buyer B,Vendor B,-1,75000,Award desc,Title,,GSIN1,2024-01-01,2024-12-31,CAD\n"
    csv_path.write_text(header + row)
    releases = ingest_csv(csv_path, ROOT / "sources/canadabuys_award_notices/mapping.yaml")
    assert releases[0]["awards"][0]["value"]["amount"] == 75000.0


def test_ontario_vor_skips_two_line_preamble_and_maps_qualified_vendor(tmp_path):
    csv_path = tmp_path / "vor.csv"
    csv_path.write_text(
        "Enterprise VOR Program export\n"
        "generated 2026-01-01\n"
        "Vendor of Record (VOR) Number, Vendor of Record (VOR) Name, Qualified Vendor, Start Date, End Date\n"
        "VOR-1,IT Staffing Arrangement,Acme Consulting Inc.,2024-01-01,2026-01-01\n"
    )
    releases = ingest_csv(csv_path, ROOT / "sources/ontario_vor/mapping.yaml")
    assert len(releases) == 1
    release = releases[0]
    assert release["awards"][0]["suppliers"][0]["name"] == "Acme Consulting Inc."
    assert release["buyer"]["jurisdiction"] == "on"
    # ontario_vor publishes no transaction value; amount must be the documented zero, never inferred.
    assert release["awards"][0]["value"]["amount"] == 0.0
    # VOR arrangements aren't GSIN/UNSPSC-classified; the scheme must say so.
    assert release["awards"][0]["items"][0]["classification"]["scheme"] == "VOR"


def test_ontario_vor_excludes_rows_missing_required_field(tmp_path):
    csv_path = tmp_path / "vor.csv"
    csv_path.write_text(
        "preamble line 1\n"
        "preamble line 2\n"
        "Vendor of Record (VOR) Number, Vendor of Record (VOR) Name, Qualified Vendor, Start Date, End Date\n"
        "VOR-1,Real Arrangement,Acme Consulting Inc.,2024-01-01,2026-01-01\n"
        ",Footer note - not a vendor row,,,\n"
    )
    releases = ingest_csv(csv_path, ROOT / "sources/ontario_vor/mapping.yaml")
    assert len(releases) == 1
    assert releases[0]["id"] == "VOR-1"


def test_canadabuys_contract_history_maps_core_fields(tmp_path):
    csv_path = tmp_path / "contract_history.csv"
    header = (
        "solicitationNumber-numeroSollicitation,referenceNumber-numeroReference,"
        "contractAwardDate-dateAttributionContrat,publicationDate-datePublication,"
        "contractingEntityName-nomEntitContractante-eng,"
        "supplierLegalName-nomLegalFournisseur-eng,supplierOperatingName-nomCommercialFournisseur-eng,"
        "contractAmount-montantContrat,totalContractValue-valeurTotaleContrat,"
        "tenderDescription-descriptionAppelOffres-eng,title-titre-eng,unspsc,gsin-nibs,"
        "contractStartDate-contratDateDebut,contractEndDate-dateFinContrat,contractCurrency-contratMonnaie\n"
    )
    row = "SOL-1,REF-1,2024-11-13,2024-11-29,Buyer C,Vendor C,Vendor C Operating,924247.00,924247.00,Tender desc,Title,,GSIN1,,2026-02-13,CAD\n"
    csv_path.write_text(header + row)
    releases = ingest_csv(csv_path, ROOT / "sources/canadabuys_contract_history/mapping.yaml")
    assert len(releases) == 1
    release = releases[0]
    assert release["ocid"] == "SOL-1"
    assert release["id"] == "REF-1"
    assert release["buyer"]["name"] == "Buyer C"
    assert release["awards"][0]["suppliers"][0]["name"] == "Vendor C"
    assert release["awards"][0]["value"]["amount"] == 924247.0
    assert release["_provenance"]["source_id"] == "canadabuys_contract_history"


def test_canadabuys_contract_history_negative_amount_falls_back_to_total_value(tmp_path):
    csv_path = tmp_path / "contract_history.csv"
    header = (
        "solicitationNumber-numeroSollicitation,referenceNumber-numeroReference,"
        "contractAwardDate-dateAttributionContrat,publicationDate-datePublication,"
        "contractingEntityName-nomEntitContractante-eng,"
        "supplierLegalName-nomLegalFournisseur-eng,supplierOperatingName-nomCommercialFournisseur-eng,"
        "contractAmount-montantContrat,totalContractValue-valeurTotaleContrat,"
        "tenderDescription-descriptionAppelOffres-eng,title-titre-eng,unspsc,gsin-nibs,"
        "contractStartDate-contratDateDebut,contractEndDate-dateFinContrat,contractCurrency-contratMonnaie\n"
    )
    row = "SOL-1,REF-1,2024-02-01,2024-01-01,Buyer D,,Vendor D Operating,-1,75000,,Title,,GSIN1,,,CAD\n"
    csv_path.write_text(header + row)
    releases = ingest_csv(csv_path, ROOT / "sources/canadabuys_contract_history/mapping.yaml")
    assert releases[0]["awards"][0]["value"]["amount"] == 75000.0
    # falls back to the operating name when the legal name is blank
    assert releases[0]["awards"][0]["suppliers"][0]["name"] == "Vendor D Operating"


def test_unknown_source_id_raises_instead_of_silently_misapplying(tmp_path):
    # A new source must get its own explicit branch; falling through to
    # another source's column logic would silently produce garbage records.
    csv_path = tmp_path / "mystery.csv"
    csv_path.write_text("colA,colB\nvalue1,value2\n")
    config_path = tmp_path / "mapping.yaml"
    config_path.write_text(
        "source_id: not_a_real_source\n"
        "jurisdiction: federal\n"
        "mapping_version: test\n"
        "mappings: []\n"
    )
    with pytest.raises(ValueError, match="no mapping implementation"):
        ingest_csv(csv_path, config_path)


def test_ingest_csv_respects_record_limit(tmp_path):
    csv_path = tmp_path / "contracts.csv"
    header = (
        "reference_number,procurement_id,vendor_name,buyer_name,contract_date,"
        "description_en,contract_period_start,delivery_date,contract_value,commodity_code\n"
    )
    rows = "".join(f"REF-{i},PROC-{i},Vendor {i},Buyer,2024-01-01,desc,2024-01-01,2024-12-31,100,X\n" for i in range(5))
    csv_path.write_text(header + rows)
    releases = ingest_csv(csv_path, ROOT / "sources/federal_contracts/mapping.yaml", limit=2)
    assert len(releases) == 2
