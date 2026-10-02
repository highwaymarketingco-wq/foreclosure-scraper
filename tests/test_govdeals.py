"""govdeals.py was rewritten 2026-10-01 (national-auction-tier audit, batch 4)
after finding two live bugs:

1. The request body used a stale `{"searchModel": {...}}` envelope with
   field names (pageNumber/pageSize/isTimeSearch) the production API no
   longer recognizes. It never 4xx'd -- it returned HTTP 200 with
   `isAPIFailureActive: true` and silently fell back to an UNFILTERED
   cross-state default result set. Reverse-engineered the real flat
   request shape from the live Angular bundle.

2. The old `_is_real_property()` substring-matched "land"/"building" and
   would have fabricated real-estate leads out of a landscaping-equipment
   auction ("Nursery/Horticulture/**Land**scaping") and a garden shed
   ("Portable **Building**s and structures") -- both have a street address
   (the seller's depot) so they would have passed the old filter cleanly.
   Fixed by scoping `categoryIds` server-side to the real taxonomy
   branches (84, 95A) instead of client-side keyword matching.

These tests pin: the real request shape, the real-estate-only category
scope (regression pin against the excluded structure-only branches), the
NC/SC state-code resolution, and the land-vs-residential `_kind()` fix (a
vacant lot's own zoning text says "Residential Low Density" and must not
make it SINGLE_FAMILY)."""
from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.national.govdeals import (
    REAL_ESTATE_CATEGORY_IDS,
    _build_payload,
    _kind,
    _to_listing,
)

# Live-captured row (2026-10-01): a genuine vacant-land parcel whose OWN
# zoning text contains the word "Residential" -- the exact shape that used
# to mislabel it as a built single-family home.
_NC_LAND_ROW = {
    "assetId": 4, "auctionId": 5,
    "assetShortDescription": "0.474 Acres on Carolina Avenue, Mount Airy, NC 27030 (PIN 501116835630)",
    "categoryDescription": "Real Estate / Land Parcels",
    "assetCategory": "84",
    "assetLongDescription": "Property Address: Carolina Avenue, Mount Airy, NC 27030 (PIN 501116835630)\n"
                             "Lot Size: 0.474-acres, more or less Zoning: RL (Residential Low Density)\n"
                             "Legally described in Deed Book 0068, Page 0022 of the Surry County Registry",
    "locationAddress1": "300 S Main St", "locationCity": "Mount Airy",
    "locationState": "NC", "locationZip": "27030-4716",
    "currentBid": 8250.0, "bidCount": 0,
    "assetAuctionEndDate": "2026-10-17T23:30:37",
    "assetAuctionStartDate": "2026-09-16T09:00:37",
    "latitude": 36.497135, "longitude": -80.607005,
    "clickUrl": None, "isSoldAuction": False, "hasReservePrice": True,
    "displaySellerName": True, "lotNumber": None,
}

# Live-captured row (2026-10-01): an actual house -- must stay SINGLE_FAMILY.
_SC_HOME_ROW = {
    "assetId": 8, "auctionId": 8,
    "assetShortDescription": "Charming residential home alongside a commercial building.",
    "categoryDescription": "Real Estate / Land Parcels",
    "assetCategory": "84",
    "assetLongDescription": "Charming residential home alongside a commercial building.",
    "locationAddress1": "207 Gilbert St", "locationCity": "Anderson",
    "locationState": "SC", "locationZip": "29624",
    "currentBid": 18000.0, "bidCount": 8,
    "assetAuctionEndDate": "2026-10-21T12:05:00",
    "assetAuctionStartDate": "2026-09-21T12:20:00",
    "clickUrl": None, "isSoldAuction": False, "hasReservePrice": True,
    "displaySellerName": "Seller 30033 - NEDZS", "lotNumber": None,
}

# The exact false-positive shape from the OLD keyword-substring bug: a
# landscaping-equipment auction whose category text contains "Land". It
# still has a real street address (the seller's depot). _to_listing() no
# longer gates on keywords at all -- that job moved server-side to
# categoryIds -- so this row would only ever reach _to_listing if the
# category scope were ever (incorrectly) widened; this fixture exists so a
# future regression is visible via test_real_estate_category_ids_exclude_structures.
_LANDSCAPING_EQUIPMENT_ROW = {
    "assetId": 99, "auctionId": 99,
    "assetShortDescription": "2022 Scag Turf Storm Spreader/Sprayer",
    "categoryDescription": "Nursery/Horticulture/Landscaping",
    "assetLongDescription": "2022 Scag Turf Storm Spreader/Sprayer, 801 Hours",
    "locationAddress1": "4355 Golf Acres Dr", "locationCity": "Charlotte",
    "locationState": "NC", "locationZip": "28208",
    "currentBid": 2675.0,
}


def test_build_payload_is_flat_with_required_nonnull_fields():
    """Regression pin for bug #1: no searchModel/businessUnit/siteId
    envelope, and facetLimit/facetsShortened must be real int/bool (the
    live API 400s with a .NET model-binding error on null)."""
    payload = _build_payload("84", "North Carolina", 1)
    assert "searchModel" not in payload
    assert "businessUnit" not in payload
    assert "siteId" not in payload
    assert payload["categoryIds"] == "84"
    assert payload["businessId"] == "GD"
    assert payload["page"] == 1
    assert isinstance(payload["facetLimit"], int)
    assert isinstance(payload["facetsShortened"], bool)
    assert payload["facetsFilter"] == ['{!tag=stateDesc}stateDesc:"North\\ Carolina"']


def test_build_payload_escapes_state_name_spaces():
    payload = _build_payload("95A", "South Carolina", 2)
    assert payload["facetsFilter"] == ['{!tag=stateDesc}stateDesc:"South\\ Carolina"']


def test_real_estate_category_ids_exclude_structure_only_branches():
    """Regression pin: 20 (Permanent Buildings) and 980 (Portable Buildings
    and structures) are siblings of 84/95A under the same GovDeals L0 node
    but are relocatable structures, not real property -- must stay excluded."""
    assert set(REAL_ESTATE_CATEGORY_IDS) == {"84", "95A"}
    assert "20" not in REAL_ESTATE_CATEGORY_IDS
    assert "980" not in REAL_ESTATE_CATEGORY_IDS


def test_vacant_land_with_residential_zoning_text_is_not_single_family():
    assert _kind(_NC_LAND_ROW) == PropertyKind.LAND


def test_actual_home_row_is_single_family():
    assert _kind(_SC_HOME_ROW) == PropertyKind.SINGLE_FAMILY


def test_nc_land_row_parses_with_address_and_bid():
    li = _to_listing(_NC_LAND_ROW, "national.govdeals")
    assert li is not None
    assert li.state == "NC"
    assert li.street_address == "300 S Main St"
    assert li.opening_bid == 8250.0
    assert li.raw["govdeals"]["category"] == "Real Estate / Land Parcels"
    assert li.raw["govdeals"]["auction_id"] == 5


def test_sc_home_row_parses():
    li = _to_listing(_SC_HOME_ROW, "national.govdeals")
    assert li is not None
    assert li.state == "SC"
    assert li.city == "Anderson"


def test_out_of_footprint_state_is_dropped():
    row = dict(_NC_LAND_ROW)
    row["locationState"] = "GA"
    assert _to_listing(row, "national.govdeals") is None
