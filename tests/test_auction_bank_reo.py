"""Parser tests for the Williams & Williams + Founders FCU REO reader.

Both fixtures are trimmed from pages fetched live on 2026-08-06, including the
two layout traps that produced wrong data on the first run.
"""
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national.auction_bank_reo import (
    body_text, parse_properties,
)

# Williams renders each row as street / city / type / date, with NO price, and
# runs straight into a "Featured Properties" block that DOES carry a price.
WILLIAMS = (
    " 3349 Herbert Dr \n Montgomery, AL 36116\r\n Foreclosure Auction \r\n Aug 12\r\n"
    " 2005 ROBYN AVE \n SHELBY, NC 28152\r\n Foreclosure Auction \r\n Aug 12\r\n"
    " 156 UZZELL RD \n HUBERT, NC 28539\r\n Foreclosure Auction \r\n Aug 12\r\n"
    " 3489 LAMP LIGHT DR \n RANDLEMAN, NC 27317\r\n Foreclosure Auction \r\n Aug 12\r\n"
    " × \r\n Featured Properties\n Residential \r\n Private Sellers\n"
    " 1914 W. Emerald Bend Court\n Price: $1,500,000\n"
)

# Founders puts the price ABOVE the address line, and the address carries a
# route number and a directional after the street type.
FOUNDERS = (
    ' Property sold "As-Is"\n 2755 US Hwy 74, Wadesboro, NC \n'
    " Price:\n $160,000\n Address:\n 2755 US Hwy 74 E, Wadesboro, NC 28170\n"
    " Contact:\n Sandra Moose, Realtor\n"
)


def _w():
    return parse_properties(WILLIAMS, "national.auction_bank_reo.williams_williams",
                            "https://www.williamsauction.com/", ListingType.AUCTION,
                            want_price=False)


def _f():
    return parse_properties(FOUNDERS, "national.auction_bank_reo.founders_fcu",
                            "https://www.foundersfcu.com/foreclosures",
                            ListingType.REO, want_price=True)


def test_only_nc_and_sc_rows_are_kept():
    """The index is national; the Alabama row must not become a lead."""
    rows = _w()
    assert {r.state for r in rows} == {"NC"}
    assert not [r for r in rows if r.city and "Montgomery" in r.city]


def test_street_does_not_absorb_the_previous_rows_date():
    """The bug: '\\s+' after the house number spanned newlines and read the
    previous row's 'Aug 12' as the street number, giving '12 2005 ROBYN AVE'."""
    streets = {r.street_address for r in _w()}
    assert "2005 ROBYN AVE" in streets
    for s in streets:
        assert not s.startswith(("11 ", "12 ")), s


def test_all_three_nc_streets_parse():
    got = {(r.street_address, r.city) for r in _w()}
    assert ("2005 ROBYN AVE", "SHELBY") in got
    assert ("156 UZZELL RD", "HUBERT") in got
    assert ("3489 LAMP LIGHT DR", "RANDLEMAN") in got


def test_williams_never_asserts_a_price():
    """The index publishes none. The last NC row sits just above a featured
    listing priced at $1,500,000 and was inheriting it."""
    for r in _w():
        assert r.raw["auction_bank_reo"]["price"] is None, r.street_address


def test_founders_reads_the_price_that_sits_above_the_address():
    rows = _f()
    assert len(rows) == 1
    assert rows[0].raw["auction_bank_reo"]["price"] == 160000.0


def test_founders_street_keeps_its_route_number_and_direction():
    """'2755 US Hwy 74 E' must not truncate to '2755 US Hwy'."""
    assert _f()[0].street_address == "2755 US Hwy 74 E"


def test_founders_row_is_reo_and_williams_is_auction():
    assert _f()[0].listing_type is ListingType.REO
    assert all(r.listing_type is ListingType.AUCTION for r in _w())


def test_duplicate_street_city_zip_is_emitted_once():
    rows = parse_properties(WILLIAMS + WILLIAMS,
                            "s", "u", ListingType.AUCTION)
    assert len({(r.street_address, r.city, r.zip_code) for r in rows}) == len(rows)


def test_zip_and_city_are_captured():
    r = [x for x in _w() if x.city == "SHELBY"][0]
    assert r.zip_code == "28152"
    assert r.foreclosure_process == "reo"


def test_body_text_preserves_line_structure():
    """Street/city pairing depends on the line break between them.

    Leading spaces per line are expected and harmless; the street regex is
    anchored with ^[ \\t]* precisely so it tolerates them. What matters is that
    the two fields do NOT end up on the same line.
    """
    out = body_text("<div>2005 ROBYN AVE</div><div>SHELBY, NC 28152</div>")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    assert "2005 ROBYN AVE" in lines
    assert "SHELBY, NC 28152" in lines
    # and the pairing still works end to end
    rows = parse_properties(out, "s", "u", ListingType.AUCTION)
    assert [(r.street_address, r.city) for r in rows] == [("2005 ROBYN AVE", "SHELBY")]
