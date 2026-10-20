"""enrichment_berkeley_vacant_lot: pure, no-network restatement of
raw['berkeley_paystar_tax']['building_count'] (the county's own CAMA structure count) into
the shared raw['vacant_lot'] contract.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_berkeley_vacant_lot import (
    build_vacant_lot_block, enrich_berkeley_vacant_lot,
)


def _li(parcel="142-08-01-040", raw=None) -> Listing:
    return Listing(source="counties_sc.berkeley_paystar_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county="Berkeley", state="SC", parcel_id=parcel, raw=raw or {})


def _blk(building_count=None, **extra) -> dict:
    blk = dict(extra)
    if building_count is not None:
        blk["building_count"] = building_count
    return blk


# ---------------------------------------------------------------------------
# build_vacant_lot_block
# ---------------------------------------------------------------------------

def test_build_block_zero_building_count_is_vacant():
    block = build_vacant_lot_block(_blk(0.0))
    assert block == {"building_count": 0, "basis": "cama_structure_count",
                      "source": "counties_sc.berkeley_paystar_tax",
                      "source_key": "berkeley_paystar_tax"}


def test_build_block_nonzero_building_count_is_none():
    assert build_vacant_lot_block(_blk(1.0)) is None
    assert build_vacant_lot_block(_blk(2.0)) is None


def test_build_block_missing_building_count_is_none_not_guessed():
    """No reading at all (field absent) must never be silently treated as 0."""
    assert build_vacant_lot_block(_blk()) is None
    assert build_vacant_lot_block({}) is None


def test_build_block_unreadable_building_count_is_none():
    assert build_vacant_lot_block(_blk("not-a-number")) is None


# ---------------------------------------------------------------------------
# enrich_berkeley_vacant_lot: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_berkeley_vacant_lot([li])
    assert stats["eligible"] == 0
    assert "vacant_lot" not in li.raw


def test_enrich_writes_for_a_real_zero_count_row():
    li = _li(raw={"berkeley_paystar_tax": _blk(0.0)})
    stats = enrich_berkeley_vacant_lot([li])
    assert stats["eligible"] == 1
    assert stats["written"] == 1
    assert li.raw["vacant_lot"]["building_count"] == 0


def test_enrich_leaves_an_improved_parcel_alone_but_counts_it_checked():
    li = _li(raw={"berkeley_paystar_tax": _blk(1.0)})
    stats = enrich_berkeley_vacant_lot([li])
    assert stats["eligible"] == 1
    assert stats["improved"] == 1
    assert "vacant_lot" not in li.raw


def test_enrich_stays_silent_with_no_reading_at_all():
    li = _li(raw={"berkeley_paystar_tax": _blk()})
    stats = enrich_berkeley_vacant_lot([li])
    assert stats["eligible"] == 1
    assert stats["no_reading"] == 1
    assert "vacant_lot" not in li.raw


def test_enrich_does_not_overwrite_an_existing_vacant_lot_block():
    sentinel = {"land_use": "VACANT LAND", "manual": True}
    li = _li(raw={"berkeley_paystar_tax": _blk(0.0), "vacant_lot": sentinel})
    stats = enrich_berkeley_vacant_lot([li])
    assert stats["eligible"] == 0
    assert li.raw["vacant_lot"] is sentinel


def test_enrich_skips_a_stray_block_on_a_non_berkeley_row():
    """Same cross-contamination guard as enrichment_berkeley_two_year_delinquent.py: the
    source key's presence alone must never be trusted; county is the real gate."""
    li = _li(parcel="0000000000", raw={"berkeley_paystar_tax": _blk(0.0, parent_tms="0000000000")})
    li.county = "Spartanburg"
    stats = enrich_berkeley_vacant_lot([li])
    assert stats["eligible"] == 0
    assert stats["skipped_wrong_county"] == 1
    assert "vacant_lot" not in li.raw
