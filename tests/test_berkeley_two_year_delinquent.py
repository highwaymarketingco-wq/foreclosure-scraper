"""enrichment_berkeley_two_year_delinquent: pure, no-network restatement of
raw['berkeley_paystar_tax']'s already-computed years_delinquent/oldest_year
(berkeley_paystar_tax._merge_invoices()'s own shape) into the shared
raw['two_year_delinquent'] contract.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_berkeley_two_year_delinquent import (
    build_two_year_block, enrich_berkeley_two_year_delinquent,
)


def _li(parcel="4192-00-96-2106", raw=None) -> Listing:
    return Listing(source="counties_sc.berkeley_paystar_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county="Berkeley", state="SC", parcel_id=parcel, raw=raw or {})


def _blk(years_delinquent, oldest_year, **extra) -> dict:
    return {"years_delinquent": years_delinquent, "oldest_year": oldest_year,
            "invoice_count": extra.pop("invoice_count", years_delinquent or 1), **extra}


# ---------------------------------------------------------------------------
# build_two_year_block
# ---------------------------------------------------------------------------

def test_build_two_year_block_multi_year():
    block = build_two_year_block(_blk(3, 2021))
    assert block == {"is_two_year_plus": True, "years": 3, "oldest_year": 2021,
                      "source": "counties_sc.berkeley_paystar_tax"}


def test_build_two_year_block_single_year_still_written_as_false():
    block = build_two_year_block(_blk(1, 2025))
    assert block == {"is_two_year_plus": False, "years": 1, "oldest_year": 2025,
                      "source": "counties_sc.berkeley_paystar_tax"}


def test_build_two_year_block_zero_matured_years():
    block = build_two_year_block(_blk(0, None))
    assert block == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                      "source": "counties_sc.berkeley_paystar_tax"}


def test_build_two_year_block_missing_fields_defaults_safely():
    assert build_two_year_block({}) == {"is_two_year_plus": False, "years": 0,
                                        "oldest_year": None,
                                        "source": "counties_sc.berkeley_paystar_tax"}


# ---------------------------------------------------------------------------
# enrich_berkeley_two_year_delinquent: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_berkeley_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert "two_year_delinquent" not in li.raw


def test_enrich_writes_for_real_shaped_row():
    li = _li(raw={"berkeley_paystar_tax": _blk(2, 2022)})
    stats = enrich_berkeley_two_year_delinquent([li])
    assert stats["eligible"] == 1
    assert stats["written"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"is_two_year_plus": True, "years": 99, "manual": True}
    li = _li(raw={"berkeley_paystar_tax": _blk(2, 2022), "two_year_delinquent": sentinel})
    stats = enrich_berkeley_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel


def test_enrich_skips_a_stray_block_on_a_non_berkeley_row():
    """2026-10-19 backfill dry-run found real board rows (Spartanburg SC, Sumter SC, both
    qpaybill_delinquent_roll-sourced) carrying a stray raw['berkeley_paystar_tax'] block with a
    junk parent_tms ("0000000000") -- a pre-existing cross-contamination bug elsewhere. The
    source key's presence alone must never be trusted; county is the real gate."""
    li = _li(parcel="0000000000", raw={"berkeley_paystar_tax": _blk(3, 2021, parent_tms="0000000000")})
    li.county = "Spartanburg"
    stats = enrich_berkeley_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert stats["skipped_wrong_county"] == 1
    assert "two_year_delinquent" not in li.raw
