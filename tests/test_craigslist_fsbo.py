"""Unit test for the Craigslist FSBO SAPI item parser — the fragile delta-id + slug decode."""
from foreclosure_scraper.scrapers.national.craigslist_fsbo import _listing_from_item, _parse_coord


# a real SAPI item shape (captured 2026-08-16): delta-id, _, cat, price, coord, code, [tag,..], title
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
