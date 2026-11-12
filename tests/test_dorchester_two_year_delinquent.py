"""enrichment_dorchester_two_year_delinquent: pure, no-network restatement of
raw['billtrax_dorchester_delinquent_tax']'s already-computed is_two_year_plus/years_delinquent
(dorchester_billtrax_delinquent_tax.py's own aggregation shape) into the shared
raw['two_year_delinquent'] contract.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_dorchester_two_year_delinquent import (
    build_two_year_block, enrich_dorchester_two_year_delinquent,
)


def _li(parcel="0123456789", raw=None) -> Listing:
    return Listing(source="counties_sc.dorchester_billtrax_delinquent_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county="Dorchester", state="SC", parcel_id=parcel, raw=raw or {})


def _blk(years, years_delinquent, is_two_year_plus, **extra) -> dict:
    return {"years": years, "years_delinquent": years_delinquent,
            "is_two_year_plus": is_two_year_plus, **extra}


# ---------------------------------------------------------------------------
# build_two_year_block
# ---------------------------------------------------------------------------

def test_build_two_year_block_copies_source_fields_directly():
    block = build_two_year_block(_blk([2022, 2023, 2024], 3, True))
    assert block == {"is_two_year_plus": True, "years": 3, "oldest_year": 2022,
                      "source": "counties_sc.dorchester_billtrax_delinquent_tax"}


def test_build_two_year_block_single_year_still_written_as_false():
    block = build_two_year_block(_blk([2025], 1, False))
    assert block == {"is_two_year_plus": False, "years": 1, "oldest_year": 2025,
                      "source": "counties_sc.dorchester_billtrax_delinquent_tax"}


def test_build_two_year_block_no_years_list():
    block = build_two_year_block({"years_delinquent": 0, "is_two_year_plus": False})
    assert block == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                      "source": "counties_sc.dorchester_billtrax_delinquent_tax"}


def test_build_two_year_block_missing_fields_defaults_safely():
    assert build_two_year_block({}) == {"is_two_year_plus": False, "years": 0,
                                        "oldest_year": None,
                                        "source": "counties_sc.dorchester_billtrax_delinquent_tax"}


# ---------------------------------------------------------------------------
# enrich_dorchester_two_year_delinquent: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_dorchester_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert "two_year_delinquent" not in li.raw


def test_enrich_writes_for_real_shaped_row():
    li = _li(raw={"billtrax_dorchester_delinquent_tax": _blk([2022, 2023], 2, True)})
    stats = enrich_dorchester_two_year_delinquent([li])
    assert stats["eligible"] == 1
    assert stats["written"] == 1
    assert li.raw["two_year_delinquent"] == {
        "is_two_year_plus": True, "years": 2, "oldest_year": 2022,
        "source": "counties_sc.dorchester_billtrax_delinquent_tax"}


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"is_two_year_plus": True, "years": 99, "manual": True}
    li = _li(raw={"billtrax_dorchester_delinquent_tax": _blk([2022, 2023], 2, True),
                 "two_year_delinquent": sentinel})
    stats = enrich_dorchester_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel
