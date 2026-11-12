"""enrichment_berkeley_rollback_exposure: pure, no-network restatement of a confirmed
RollbackCode=="R" realized ag-use rollback bill (raw['berkeley_paystar_tax']'s own
rollback_code/rollback_description/rollback_information/rollback_use_change_year fields)
into the shared raw['rollback_exposure'] contract.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_berkeley_rollback_exposure import (
    build_rollback_block, enrich_berkeley_rollback_exposure,
)


def _li(parcel="081-00-00-141", raw=None) -> Listing:
    return Listing(source="counties_sc.berkeley_paystar_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county="Berkeley", state="SC", parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_rollback_block
# ---------------------------------------------------------------------------

def test_build_block_real_rollback_code_shape():
    """Shape of a real live invoice (081-00-00-141, 2026-10-20 live check)."""
    blk = {"rollback_code": "R", "rollback_description": "MH40093",
           "rollback_information": "ROLLBACK TAXES", "rollback_use_change_year": "2025",
           "total_due": 241.34, "latest_invoice_total_due": 241.34, "tax_year": 2025}
    block = build_rollback_block(blk)
    assert block["basis"] == "realized_rollback_bill"
    assert block["rollback_code"] == "R"
    assert block["amount_due"] == 241.34
    assert block["trigger"] == "MH40093"
    assert block["rollback_information"] == "ROLLBACK TAXES"
    assert block["use_change_year"] == "2025"
    assert block["tax_year"] == 2025
    assert block["estimate_is_floor"] is False


def test_build_block_no_rollback_code_is_none():
    assert build_rollback_block({"taxes_due": 300.0}) is None
    assert build_rollback_block({"rollback_code": ""}) is None


def test_build_block_other_rollback_codes_are_not_assumed_positive():
    """Only the one live-confirmed positive value ("R") counts -- a different code is never
    guessed to mean the same thing."""
    assert build_rollback_block({"rollback_code": "X"}) is None


def test_build_block_missing_amount_omits_amount_due_rather_than_zero():
    block = build_rollback_block({"rollback_code": "R"})
    assert block is not None
    assert "amount_due" not in block


# ---------------------------------------------------------------------------
# enrich_berkeley_rollback_exposure: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_berkeley_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert "rollback_exposure" not in li.raw


def test_enrich_writes_for_a_real_rollback_row():
    li = _li(raw={"berkeley_paystar_tax": {"rollback_code": "R", "total_due": 902.16}})
    stats = enrich_berkeley_rollback_exposure([li])
    assert stats["eligible"] == 1
    assert stats["written"] == 1
    assert li.raw["rollback_exposure"]["basis"] == "realized_rollback_bill"


def test_enrich_leaves_non_rollback_rows_alone():
    li = _li(raw={"berkeley_paystar_tax": {"taxes_due": 300.0}})
    stats = enrich_berkeley_rollback_exposure([li])
    assert stats["eligible"] == 1
    assert stats["no_rollback"] == 1
    assert "rollback_exposure" not in li.raw


def test_enrich_does_not_overwrite_an_existing_block():
    sentinel = {"basis": "present_use_deferral", "manual": True}
    li = _li(raw={"berkeley_paystar_tax": {"rollback_code": "R"}, "rollback_exposure": sentinel})
    stats = enrich_berkeley_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert li.raw["rollback_exposure"] is sentinel


def test_enrich_skips_a_stray_block_on_a_non_berkeley_row():
    """Same cross-contamination guard as enrichment_berkeley_two_year_delinquent.py: the
    source key's presence alone must never be trusted; county is the real gate."""
    li = _li(parcel="0000000000",
              raw={"berkeley_paystar_tax": {"rollback_code": "R", "parent_tms": "0000000000"}})
    li.county = "Spartanburg"
    stats = enrich_berkeley_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert stats["skipped_wrong_county"] == 1
    assert "rollback_exposure" not in li.raw
