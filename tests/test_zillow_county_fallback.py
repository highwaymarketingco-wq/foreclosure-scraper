"""national.zillow_foreclosures and national.zillow_bulk: 2026-10-01
national/reo per-source extraction audit.

Zillow's hdpData.homeInfo.county is blank on most rows -- confirmed live,
282/310 NC zillow_foreclosures rows (91%) had no county at all. This is a
severe, silent lead-loss bug: FORECLOSURE_SALE/AUCTION/REO are all "flip"
listing types (main._FLIP_LISTING_TYPES), which gate on the NARROW
in_scope(county, state) check, and in_scope(None, state) is unconditionally
False -- so a real in-footprint lead with no county had no chance of
admission at all, e.g. "208 S Ransom St, Gastonia NC" (Gaston county) and
"71 Laurel Ridge Dr, Spruce Pine NC" (Mitchell county), both live-confirmed
present in a real fetch and both in the 18-county footprint.

Only a coastal fallback existed before; upstate_county_for (the WNC/
upstate-SC gazetteer already used by national.crexi_multifamily and
national.estate_sales for this exact problem) is now tried first. Live
re-verification after the fix: missing-county NC rows dropped from 282/310
to 151/310, with Gastonia/Spruce Pine rows correctly resolving to
Gaston/Mitchell.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national import zillow_bulk as bulk_mod
from foreclosure_scraper.scrapers.national import zillow_foreclosures as fc_mod


def _item(city: str, state: str = "NC", street: str = "1 Test St") -> dict:
    return {
        "addressStreet": street,
        "addressCity": city,
        "addressState": state,
        "addressZipcode": "28052",
        "zpid": "12345",
        "unformattedPrice": 150000,
        "hdpData": {"homeInfo": {}},  # county always blank, as confirmed live
        "marketingStatusSimplifiedCd": "Foreclosure",
    }


def test_zillow_foreclosures_resolves_upstate_city_to_county():
    li = fc_mod._to_listing(_item("Gastonia"), "NC", "national.zillow_foreclosures")
    assert li is not None
    assert li.county == "Gaston"


def test_zillow_foreclosures_resolves_wnc_city_to_county():
    li = fc_mod._to_listing(_item("Spruce Pine"), "NC", "national.zillow_foreclosures")
    assert li is not None
    assert li.county == "Mitchell"


def test_zillow_foreclosures_out_of_footprint_city_stays_none():
    """A genuinely out-of-footprint city (not in either gazetteer) must NOT
    get a fabricated county -- confirms the fix doesn't over-admit."""
    li = fc_mod._to_listing(_item("Nowhereville"), "NC", "national.zillow_foreclosures")
    assert li is not None
    assert li.county is None


def test_zillow_bulk_resolves_upstate_city_to_county():
    li = bulk_mod._to_listing(_item("Gastonia"), "NC", "national.zillow_bulk")
    assert li is not None
    assert li.county == "Gaston"


def test_explicit_county_from_api_still_wins_over_the_gazetteer():
    item = _item("Gastonia")
    item["hdpData"]["homeInfo"]["county"] = "Mecklenburg County"
    li = fc_mod._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li.county == "Mecklenburg"
