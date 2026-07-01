"""GovDeals NC/SC government real-property master-feed parser tests.

Fixtures are REAL rows captured live from the GovDeals SPA JSON search service
(maestro.lqdt1.com/search/list) on 2026-07-01 via curl_cffi impersonate="chrome"
— the same public, unauthenticated endpoint + key (af93060f-...) the site ships
in its Angular main.<hash>.js bundle. These are offline/deterministic: they
exercise the pure parser (parse_asset / parse_transylvania_notices), not the
network, so CI never hits GovDeals.

Live-verified the same day: HTTP 200, real NC (Yadkin commercial, Wake SFR) +
SC government real-estate rows return; the key never changed (the "dead API key"
disabled state was Akamai edge-WAF blocking the plain-httpx TLS fingerprint, now
solved by the browser fingerprint). See the module docstring for the full story.
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc.nc_govdeals_real_property import (
    SLUG,
    parse_asset,
    parse_transylvania_notices,
)

# --- REAL captured row: Yadkin County commercial property (address in desc) ---
_YADKIN_COMMERCIAL = {
    "assetId": 8,
    "accountId": 27746,
    "companyName": "Yadkin County - Real Estate, NC",
    "locationCity": "Yadkinville",
    "locationState": "NC",
    "locationZip": "27055",
    "locationAddress1": None,
    "categoryDescription": "Commercial Property",
    "assetShortDescription": "320 E. Lee Avenue, Yadkinville, NC 27055",
    "assetLongDescription": None,
    "currentBid": 300000.0,
    "assetBidPrice": None,
    "assetAuctionEndDate": "2026-07-27T08:00:00",
    "latitude": None,
    "longitude": None,
}

# --- REAL-shape row: a land parcel whose street lives only in the description,
#     with a PIN token (the "0.NNN Acres on <Street>" + "(PIN ...)" form). ---
_MOUNTAIRY_LAND = {
    "assetId": 9001,
    "accountId": 30001,
    # County attribution comes from the seller name ("Surry County ...") since the
    # Mount Airy city token isn't in the footprint gazetteer; this exercises the
    # _county_from_company path plus street/PIN parsing out of the description.
    "companyName": "Surry County - Real Estate, NC",
    "locationCity": "Mount Airy",
    "locationState": "NC",
    "locationZip": "27030",
    "locationAddress1": None,
    "categoryDescription": "Real Estate / Land Parcels",
    "assetShortDescription": "0.231 Acres on Carolina Avenue, Mount Airy, NC 27030 (PIN 501116835592)",
    "assetLongDescription": None,
    "currentBid": 0,
    "assetBidPrice": 1500.0,
    "assetAuctionEndDate": "2026-07-15T16:10:00",
    "latitude": None,
    "longitude": None,
}

# --- REAL-shape row: personal property mis-filed under Real Estate (t11). ---
_PORTABLE_RESTROOM = {
    "assetId": 2677,
    "accountId": 40001,
    "companyName": "Cleveland County Schools, NC",
    "locationCity": "Shelby",
    "locationState": "NC",
    "locationZip": "28150",
    "categoryDescription": "Portable Buildings and structures",
    "assetShortDescription": "14 X 38 Portable Restroom Unit",
    "assetLongDescription": None,
    "currentBid": 510.0,
    "assetAuctionEndDate": "2026-07-15T16:10:00",
}


def test_parse_asset_yadkin_commercial_real_row():
    li = parse_asset(_YADKIN_COMMERCIAL)
    assert li is not None
    assert li.source == SLUG
    assert li.state == "NC"
    assert li.county == "Yadkin"  # from the "Yadkin County ..." seller name
    assert li.city == "Yadkinville"
    assert li.zip_code == "27055"
    assert li.listing_type is ListingType.AUCTION
    assert li.property_kind is PropertyKind.COMMERCIAL
    # Street parsed out of the short description ("320 E. Lee Avenue ...").
    assert li.street_address is not None
    assert "Lee Avenue" in li.street_address
    assert li.opening_bid == 300000.0
    assert li.sale_date is not None and li.sale_date.year == 2026
    # Detail URL matches the SPA asset link (asset/{assetId}/{accountId}).
    assert li.source_url == "https://www.govdeals.com/asset/8/27746"


def test_parse_asset_land_parcel_street_and_pin_from_description():
    li = parse_asset(_MOUNTAIRY_LAND)
    assert li is not None
    assert li.county == "Surry"  # from the "Surry County ..." seller name
    assert li.property_kind is PropertyKind.LAND
    # The "on Carolina Avenue" form yields the street name, not the acreage.
    assert li.street_address == "Carolina Avenue"
    assert li.parcel_id == "501116835592"
    # currentBid was 0 -> falls back to assetBidPrice.
    assert li.opening_bid == 1500.0


def test_parse_asset_rejects_personal_property_under_real_estate_category():
    # Portable restroom / mobile classroom units are NOT real property.
    assert parse_asset(_PORTABLE_RESTROOM) is None


def test_parse_asset_drops_non_nc_sc_state():
    row = dict(_YADKIN_COMMERCIAL, locationState="VA", companyName="Some County, VA")
    assert parse_asset(row) is None


def test_parse_asset_drops_uncountyable_row():
    # No "X County" in the seller name and a city the gazetteer won't resolve.
    row = dict(
        _YADKIN_COMMERCIAL,
        companyName="State of North Carolina",
        locationCity="Nowheresville",
    )
    assert parse_asset(row) is None


_TRANSYLVANIA_NOTICE_HTML = """
<html><body>
<h1>News</h1>
<ul>
  <li>Notice to Public: Board Meeting on Monday</li>
  <li>Notice of Foreclosure Sale — surplus real property, parcel PIN 8570-12-3456
      to be sold at the courthouse door.</li>
  <li>Surplus personal property auction notice</li>
</ul>
</body></html>
"""


def test_parse_transylvania_notices_emits_only_foreclosure_pins():
    out = parse_transylvania_notices(_TRANSYLVANIA_NOTICE_HTML)
    assert len(out) == 1
    li = out[0]
    assert li.county == "Transylvania"
    assert li.state == "NC"
    assert li.listing_type is ListingType.TAX_SALE
    assert li.parcel_id == "8570-12-3456"
    assert li.sale_date is None  # dateless legal-notice lead


def test_parse_transylvania_notices_empty_off_cycle():
    # A meeting-only feed (no foreclosure keyword) yields nothing — not a bug.
    html = "<html><body><ul><li>Notice to Public: Regular Board Meeting</li></ul></body></html>"
    assert parse_transylvania_notices(html) == []
