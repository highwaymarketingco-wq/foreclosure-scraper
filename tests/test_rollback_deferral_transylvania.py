"""enrichment_transylvania_rollback_exposure: a pure, no-network restatement of the county's own
labelled "Deferred Value :" line (already read by scrapers/counties_nc/transylvania_delinquent_tax.py's
ViewTaxBill parse, raw['transylvania_tax']['deferred_value']) into the shared raw['rollback_exposure']
contract.

The dollar figures below are read straight off the live board (board_stream over
docs/listings.json.gz, 2026-10-19), not invented: three real Transylvania rows currently carry a
positive deferred_value, and this fixture is the first of them (parcel 9516-38-1784-000).
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_transylvania_rollback_exposure as mod
from datetime import datetime

#: live-pulled 2026-10-19 (see this module's own docstring).
_REAL_BLOCK = {
    "tax_year": 2025,
    "deferred_value": 461410.0,
    "net_taxable_valuation": 628002.0,
    "parcel_value_total": 1073050.0,
    "bills": [{"year": 2025, "bill": "12330", "balance": 540.32, "original_levy": 3025.42}],
}
_RATE = 3025.42 / 628002.0


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(source="test", source_url="https://example.test",
               listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.SINGLE_FAMILY,
               first_seen=now, last_seen=now)
    base.update(kw)
    return Listing(**base)


def test_build_block_reproduces_the_real_deferred_value_and_rate():
    rec = mod.build_block(_REAL_BLOCK)
    assert rec["deferred_value"] == 461410.0
    assert rec["basis"] == "present_use_deferral"
    assert rec["county"] == "Transylvania" and rec["state"] == "NC"
    assert rec["rollback_years"] == 4
    assert rec["tax_year"] == 2025
    assert round(rec["effective_tax_rate"], 6) == round(_RATE, 6)
    assert rec["annual_deferred_tax"] == round(461410.0 * _RATE, 2)
    assert rec["estimated_rollback"] == round(round(461410.0 * _RATE, 2) * 4, 2)


def test_build_block_never_invents_a_deferral_when_the_field_is_blank_or_zero():
    assert mod.build_block({"net_taxable_valuation": 100000.0, "bills": []}) is None
    assert mod.build_block({"deferred_value": 0, "net_taxable_valuation": 100000.0}) is None
    assert mod.build_block({"deferred_value": None}) is None


def test_build_block_keeps_the_deferred_value_without_a_rate_when_the_rate_is_unavailable():
    rec = mod.build_block({"deferred_value": 50000.0})
    assert rec["deferred_value"] == 50000.0
    assert "estimated_rollback" not in rec
    assert "effective_tax_rate" not in rec


def test_build_block_drops_an_out_of_band_rate_but_keeps_the_deferred_value():
    # levy >> net_taxable_valuation -> a nonsense rate, must not be trusted.
    rec = mod.build_block({"deferred_value": 50000.0, "net_taxable_valuation": 100.0,
                           "bills": [{"original_levy": 500.0}]})
    assert rec["deferred_value"] == 50000.0
    assert "estimated_rollback" not in rec


def test_enrich_stamps_a_matched_row_and_is_idempotent():
    li = _lead(county="Transylvania", state="NC", parcel_id="9516-38-1784-000",
              raw={"transylvania_tax": dict(_REAL_BLOCK)})
    stats = mod.enrich_transylvania_rollback_exposure([li])
    assert stats["eligible"] == 1 and stats["matched"] == 1 and stats["with_estimate"] == 1
    rec = li.raw["rollback_exposure"]
    assert rec["deferred_value"] == 461410.0 and rec["match_method"] == "parcel"

    # Idempotent: a second pass must not re-run (already_done gate) or change the stamp.
    stats2 = mod.enrich_transylvania_rollback_exposure([li])
    assert stats2["eligible"] == 0
    assert li.raw["rollback_exposure"] == rec


def test_a_row_with_no_deferral_is_left_untouched():
    li = _lead(county="Transylvania", state="NC", parcel_id="1234567890",
              raw={"transylvania_tax": {"deferred_value": 0, "net_taxable_valuation": 50000.0}})
    stats = mod.enrich_transylvania_rollback_exposure([li])
    assert stats["eligible"] == 1 and stats["matched"] == 0 and stats["no_deferral"] == 1
    assert "rollback_exposure" not in li.raw


def test_a_row_without_the_source_block_is_never_touched():
    li = _lead(county="Transylvania", state="NC", parcel_id="1234567890", raw={})
    stats = mod.enrich_transylvania_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert "rollback_exposure" not in li.raw


def test_a_row_that_already_carries_rollback_exposure_from_another_source_is_left_alone():
    existing = {"deferred_value": 1.0, "county": "Buncombe"}
    li = _lead(county="Transylvania", state="NC", parcel_id="1234567890",
              raw={"transylvania_tax": dict(_REAL_BLOCK), "rollback_exposure": existing})
    stats = mod.enrich_transylvania_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert li.raw["rollback_exposure"] == existing
