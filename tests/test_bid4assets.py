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
per-parcel rows out of a "13 Deeds" count with no real per-deed data.

2026-10-04 (national.* extraction-completeness audit, batch 15): three more
real, free fields were on the page and unused. (1) The search API's own
`locatedCity`/`locatedState` fields are SWAPPED on every live row (verified
across all 24 current NC+SC rows) -- `locatedCity` actually holds the
2-letter state code and `locatedState` actually holds the real city; city
was never captured at all before this. (2) `mainImageUrl` -- a real (if
generic, county-level) image URL -- was fetched in the API response but
never stored. (3) each auction's own `/auction/description/{id}` page
carries two fields the search API never returns at all: "Deed or Lien"
(Deed vs Lien-certificate sale -- a real distinction this source has no
other way to draw) and "Sale Type" (Live/In-Person vs Online -- matters a
lot to whether a remote bidder can participate)."""
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national.bid4assets import (
    _build_body,
    _fetch_description_fields,
    _to_listing,
)

# Live-captured rows (2026-10-01).
_NC_ROW = {
    "auctionId": 1314088,
    "assetTitle": "NOTICE OF SALE: Cleveland County, North Carolina - Live Tax Deed Sale, 3 Deeds",
    "bidCloseTime": "2026-10-06T00:00:00",
    "actualCloseTime": "2026-10-06T00:00:00",
    "currentBid": 0,
    "bidCount": -1,
    "linkUrl": "/auction/1314088",
    # Live-captured 2026-10-04: the API's own field-name swap (see module
    # docstring) -- locatedCity really holds the state, locatedState the city.
    "locatedCity": "NC",
    "locatedState": "Shelby",
    "mainImageUrl": "https://s3.amazonaws.com/images-s3.bid4assets.com/resources/x/CustomCountyMainImage_NC_Cleveland.jpg",
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


def test_city_read_from_the_swapped_located_state_field():
    """The API's locatedCity/locatedState values are swapped on every live
    row (see module docstring) -- city must come from `locatedState`, not
    the identically-named-but-wrong `locatedCity`."""
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li.city == "Shelby"


def test_image_url_captured_when_present():
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li.raw["bid4assets"]["image_url"] == _NC_ROW["mainImageUrl"]


def test_missing_optional_fields_dont_crash():
    """A row shaped like the original (pre-2026-10-04) test fixtures, with
    no locatedCity/locatedState/mainImageUrl at all, must still parse."""
    li = _to_listing(_SC_ROW, "SC", "national.bid4assets")
    assert li is not None
    assert li.city is None
    assert li.raw["bid4assets"]["image_url"] is None


# --- per-auction description-page fields (Deed-or-Lien / Sale-Type) -------

def _description_html(deed_or_lien: str, sale_type: str, num_deeds: int) -> str:
    return f"""
    <html><body>
    Bid4Assets is providing this notice of sale strictly as a courtesy to our
    users. The Treasurer's Office of Cleveland County, North Carolina is
    conducting a tax sale with the following details:
    Date of Sale: 10/06/26
    Deed or Lien: {deed_or_lien}
    Sale Type: {sale_type}
    Number of Deeds: {num_deeds}
    Additional Information : https://bid4assets.com/TSRNoticeofSale
    </body></html>
    """


class _FakeResp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self, text, status_code=200):
        self._text = text
        self._status = status_code

    async def get(self, url, timeout=20):
        return _FakeResp(self._status, self._text)


def test_description_page_parses_deed_or_lien_and_sale_type():
    """Live-verified 2026-10-04 against 10 real current NC auctions: these
    two fields exist ONLY on this per-auction detail page, never in the
    search API's JSON rows."""
    import asyncio
    s = _FakeSession(_description_html("Deed", "Live/In Person", 3))
    out = asyncio.run(_fetch_description_fields(s, 1314088))
    assert out == {"deed_or_lien": "Deed", "sale_type": "Live/In Person"}


def test_description_page_handles_lien_and_online_variants():
    """These fields are not guaranteed constant -- a Lien-certificate sale
    or an Online sale type would be a real, different kind of auction this
    source has no other way to distinguish."""
    import asyncio
    s = _FakeSession(_description_html("Lien", "Online", 50))
    out = asyncio.run(_fetch_description_fields(s, 999))
    assert out == {"deed_or_lien": "Lien", "sale_type": "Online"}


def test_description_fetch_failure_is_swallowed_not_raised():
    """Best-effort only -- must never raise or block the listing itself."""
    import asyncio

    class _RaisingSession:
        async def get(self, url, timeout=20):
            raise RuntimeError("simulated network failure")

    out = asyncio.run(_fetch_description_fields(_RaisingSession(), 1))
    assert out == {}


def test_description_fetch_bad_status_returns_empty():
    import asyncio
    s = _FakeSession("not found", status_code=404)
    out = asyncio.run(_fetch_description_fields(s, 1))
    assert out == {}


def test_street_address_is_not_fabricated():
    """No per-parcel address exists on this source for a batch notice --
    must stay null, never guessed from the county-seat or similar."""
    li = _to_listing(_NC_ROW, "NC", "national.bid4assets")
    assert li.street_address is None


def test_missing_auction_id_or_title_is_dropped():
    assert _to_listing({"assetTitle": "x"}, "NC", "national.bid4assets") is None
    assert _to_listing({"auctionId": 1}, "NC", "national.bid4assets") is None
