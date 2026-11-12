"""County eviction-pressure attribution — LSC aggregate as market context."""
from __future__ import annotations

from foreclosure_scraper.enrichment_eviction_market import enrich_eviction_market, _table
from foreclosure_scraper.models import Listing, ListingType


def _li(state, county):
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state=state, county=county)


def test_data_file_loads_footprint():
    t = _table()
    assert len(t) >= 15  # 17 footprint counties
    assert "NC:Gaston" in t and "SC:Spartanburg" in t


def test_attributes_rate_and_tier():
    leads = [_li("NC", "Gaston"), _li("SC", "Spartanburg County"), _li("NC", "Polk")]
    stats = enrich_eviction_market(leads)
    assert stats["tagged"] == 3 and stats["high"] >= 1
    g = leads[0].raw["eviction_market"]
    assert g["tier"] == "high" and g["rate"] > 20 and g["source"] == "lsc_ccdi"
    # "Spartanburg County" resolves (suffix stripped)
    assert leads[1].raw["eviction_market"]["tier"] == "high"
    # low-rate county tiers low
    assert leads[2].raw["eviction_market"]["tier"] == "low"


def test_out_of_footprint_untagged():
    li = _li("NC", "Wake")  # not in the footprint table
    enrich_eviction_market([li])
    assert "eviction_market" not in (li.raw or {})
