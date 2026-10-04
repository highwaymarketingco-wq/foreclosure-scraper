"""Unit test for the Craigslist FSBO SAPI item parser — the fragile delta-id + slug decode.

2026-10-04 (national.* extraction-completeness audit, batch 15): found and
fixed three real gaps in `_listing_from_item`, each live-verified against
the real SAPI response. (1) Every listing with photos carries a `[4,
"3:<tok>", ...]` subarray of real image tokens -- 1-12 observed live --
completely unused before this fix; a token's own content, with the leading
flag dropped and a size suffix appended, is a real fetchable JPEG URL
(confirmed live: 200, image/jpeg). (2) A `[5, beds, sqft]` subarray (also
previously unused) carries real bedroom count + square footage, cross-
checked against each listing's own title text -- but the sqft figure is
LOT size, not living area, on a bedrooms=0 (vacant land) row, so it's only
promoted to Listing.living_sqft when bedrooms > 0. (3) `item[3] == -1` is
CL's own "no price listed" sentinel (confirmed: that shape never also
carries the formatted `[10, "$..."]` subarray every real-priced row has)
and was being surfaced as a literal -$1 listing price before this fix."""
from foreclosure_scraper.scrapers.national.craigslist_fsbo import _listing_from_item, _parse_coord


# a real SAPI item shape (captured 2026-08-16): delta-id, _, cat, price, coord, code, [tag,..], title
# [5, 0, 48787] = 0 bedrooms, 48787 sqft -- a VACANT LOT (1.12 acres == 48,787 sqft exactly),
# so bedrooms=0 means the sqft figure is LOT size, not living area (see module docstring).
ITEM = [5467174, 3351411, 143, 14500, "1:1~35.2584~-83.3411", "0cw0dS",
        [13, "rCXH81N57EJWWyyqkYnmS4"], [4, "3:00C0C_x", "3:00o0o_y"],
        [6, "franklin-franklin-nc-area-vacant"], [10, "$14,500"],
        "Franklin NC Area - Vacant building lot -- 1.12 Acres", [5, 0, 48787]]
MIN_PID = 7945853077


def test_parse_coord():
    assert _parse_coord("1:1~35.2584~-83.3411") == (35.2584, -83.3411)
    assert _parse_coord("garbage") == (None, None)


def test_item_builds_correct_url_and_fields():
    li = _listing_from_item(ITEM, "asheville.craigslist.org", MIN_PID)
    assert li is not None
    # real posting id is delta-encoded: minPostingId + item[0]
    assert li.raw["craigslist"]["posting_id"] == 7951320251
    assert li.source_url == ("https://asheville.craigslist.org/reo/d/"
                             "franklin-franklin-nc-area-vacant/7951320251.html")
    assert li.raw["craigslist"]["list_price"] == 14500
    assert "Franklin NC Area" in li.raw["craigslist"]["title"]
    assert li.state == "NC"        # lat 35.26 > 35.0
    assert li.latitude == 35.2584


def test_out_of_footprint_item_dropped():
    tx = list(ITEM)
    tx[4] = "1:1~30.3009~-98.0483"   # Texas — outside NC/SC bbox
    assert _listing_from_item(tx, "austin.craigslist.org", MIN_PID) is None


def test_sc_state_inference_below_border():
    sc = list(ITEM)
    sc[4] = "1:1~33.8299~-79.4783"   # Myrtle Beach SC
    li = _listing_from_item(sc, "myrtlebeach.craigslist.org", MIN_PID)
    assert li is not None and li.state == "SC"


# --- 2026-10-04 fixes: images, bedrooms/sqft, price sentinel ---------------

def test_image_urls_are_recovered_from_the_tagged_subarray():
    li = _listing_from_item(ITEM, "asheville.craigslist.org", MIN_PID)
    assert li.raw["craigslist"]["images"] == [
        "https://images.craigslist.org/00C0C_x_600x450.jpg",
        "https://images.craigslist.org/00o0o_y_600x450.jpg",
    ]
    assert li.raw["craigslist"]["image_url"] == "https://images.craigslist.org/00C0C_x_600x450.jpg"


def test_no_image_subarray_yields_empty_list_not_a_crash():
    no_img = [i for i in ITEM if not (isinstance(i, list) and i and i[0] == 4)]
    li = _listing_from_item(no_img, "asheville.craigslist.org", MIN_PID)
    assert li.raw["craigslist"]["images"] == []
    assert li.raw["craigslist"]["image_url"] is None


def test_vacant_lot_bedrooms_zero_does_not_mislabel_lot_size_as_living_sqft():
    """[5, 0, 48787] on a 'vacant building lot' listing -- 48,787 sqft is
    exactly 1.12 acres, i.e. LOT size. bedrooms=0 means no structure, so
    this must NOT land in Listing.living_sqft, but the raw pair is kept."""
    li = _listing_from_item(ITEM, "asheville.craigslist.org", MIN_PID)
    assert li.bedrooms == 0
    assert li.living_sqft is None
    assert li.raw["craigslist"]["bedrooms"] == 0
    assert li.raw["craigslist"]["sqft"] == 48787


def test_real_structure_promotes_bedrooms_and_sqft_to_top_level():
    """A listing with bedrooms > 0 IS a real structure -- the sqft figure
    should promote to Listing.living_sqft (live example: 'Tiny Home... ' ->
    [5, 1, 600])."""
    home = list(ITEM)
    home[-1] = [5, 1, 600]
    li = _listing_from_item(home, "asheville.craigslist.org", MIN_PID)
    assert li.bedrooms == 1
    assert li.living_sqft == 600


def test_no_price_sentinel_minus_one_is_never_a_negative_price():
    """item[3] == -1 is CL's 'no price listed' sentinel (confirmed live:
    that shape never also carries the formatted [10, "$..."] subarray a
    real-priced row has) -- must never surface as a literal -$1 price."""
    no_price = [x for x in ITEM if not (isinstance(x, list) and x and x[0] == 10)]
    no_price[3] = -1
    li = _listing_from_item(no_price, "asheville.craigslist.org", MIN_PID)
    assert li is not None
    assert li.raw["craigslist"]["list_price"] is None
    assert li.raw["craigslist"]["raw_price_sentinel"] == -1


def test_zero_price_also_treated_as_no_price():
    zero_price = list(ITEM)
    zero_price[3] = 0
    li = _listing_from_item(zero_price, "asheville.craigslist.org", MIN_PID)
    assert li.raw["craigslist"]["list_price"] is None
