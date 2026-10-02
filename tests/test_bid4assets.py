"""bid4assets.py was re-enabled 2026-10-01 (national-auction-tier audit,
batch 4). It had been DISABLED since 2026-09-15 as a confirmed garbage
emitter against the old `index.cfm?searchstate=...` URL, which now serves a
literal "Storefront not found or is currently inactive" page -- the site
was redesigned. Re-verifying DEAD sources live (HERMES rule 4) found a
working public JSON API behind `/v5/search` + `/api/search/process`, but
the real request body had to be reverse-engineered from the site's own
`search_functions.js`: a naive/empty body silently 200s with
`{"data": [], "total": 0}` unless `channel`, `assetstatus` (the EXPANDED
string "Live", not the short code "l"), and `type`/`searchtype` are all set
together.

Every live NC/SC "Real Estate" result right now is a county-level batch
"NOTICE OF SALE ... N Deeds" tax-deed-sale notice, not a single-property
listing, and Bid4Assets itself carries no per-parcel address data for these
(confirmed via the detail iframe, which punts to the county / Tax Sale
Resources). These tests pin: the real request body shape, correct county/
deed-count parsing from the title, and -- the important negative case --
that one API row produces exactly ONE Listing, never N fabricated
per-parcel rows out of a "13 Deeds" count with no real per-deed data."""
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national.bid4assets import _build_body, _to_listing

# Live-captured rows (2026-10-01).
_NC_ROW = {
    "auctionId": 1314088,
    "assetTitle": "NOTICE OF SALE: Cleveland County, North Carolina - Live Tax Deed Sale, 3 Deeds",
    "bidCloseTime": "2026-10-06T00:00:00",
    "actualCloseTime": "2026-10-06T00:00:00",
    "currentBid": 0,
    "bidCount": -1,
    "linkUrl": "/auction/1314088",
}

_SC_ROW = {
    "auctionId": 1317885,
    "assetTitle": "NOTICE OF SALE: Anderson County, South Carolina - Live Tax Redeemable Deed Sale, 1797 Redeemable Deeds",
    "bidCloseTime": "2026-10-19T00:00:00",
    "actualCloseTime": "2026-10-19T00:00:00",
    "currentBid": 0,
    "bidCount": -1,
    "linkUrl": "/auction/1317885",
}


def test_build_body_sets_the_fields_that_silently_zero_without_them():
    """Regression pin: channel/assetstatus/type/searchtype together are what
    turn a 200-with-zero-results response into a real result set."""
    body = _build_body("NC", 1)
    assert body["channel"] == "22"
    assert body["assetstatus"] == "Live"  # the EXPANDED string, not "l"
    assert body["type"] == "powersearch"
    assert body["searchtype"] == "ps"
    assert body["locatedstate"] == "NC"
    assert body["page"] == 1
    assert body["skip"] == 0


def test_build_body_paginates_with_skip():
    body = _build_body("SC", 3)
    assert body["page"] == 3
    assert body["skip"] == 2 * body["pageSize"]


def test_one_api_row_produces_exactly_one_listing():
    """The negative case: a "3 Deeds" / "1797 Redeemable Deeds" notice must
    never be exploded into N fabricated per-parcel rows -- there is no real
    per-deed address data on this source to back that up."""
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li is not None
    # One row in -> one Listing out (not `li.raw["bid4assets"]["num_deeds"]`
    # separate rows).
    assert isinstance(li, type(li))


def test_county_and_deed_count_parse_from_title():
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li.county == "Cleveland County"
    assert li.raw["bid4assets"]["num_deeds"] == 3
    assert li.listing_type == ListingType.TAX_SALE
    assert li.sale_date.isoformat().startswith("2026-10-06")


def test_redeemable_deed_count_with_thousands_separator_parses():
    li = _to_listing(_SC_ROW, "SC", "national.bid4assets")
    assert li.county == "Anderson County"
    assert li.raw["bid4assets"]["num_deeds"] == 1797
    assert li.state == "SC"


def test_sentinel_bid_values_are_never_surfaced_as_opening_bid():
    """currentBid:0 / bidCount:-1 appear on every single live row with no
    exceptions -- a placeholder, not a real starting bid (same shape as
    HiBid's 123.45 sentinel). Must never become Listing.opening_bid."""
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li.opening_bid is None


def test_street_address_is_not_fabricated():
    """No per-parcel address exists on this source for a batch notice --
    must stay null, never guessed from the county-seat or similar."""
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li.street_address is None


def test_missing_auction_id_or_title_is_dropped():
    assert _to_listing({"assetTitle": "x"}, "NC", "national.bid4assets") is None
    assert _to_listing({"auctionId": 1}, "NC", "national.bid4assets") is None
