"""Parser tests for the Williams & Williams + Founders FCU REO reader.

Both fixtures are trimmed from pages fetched live on 2026-08-06, including the
two layout traps that produced wrong data on the first run.
"""
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national.auction_bank_reo import (
    _FOUNDERS_CARD_SELECTOR,
    _WW_CARD_SELECTOR,
    _WW_DETAIL_SELECTOR,
    _parse_cards,
    _real_image_urls,
    body_text,
    parse_properties,
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


# ---- DOM-based per-card photo wiring (2026-10-02 per-source audit) --------------
#
# Fixtures below are trimmed from the real bid.auctionnetwork.com and
# foundersfcu.com pages fetched live 2026-10-02, keeping each real listing
# card's own structure (including a neighboring icon <img>) so a test failure
# here means the live markup actually changed.

# Two Williams & Williams cards: a non-footprint WV one (to prove it's
# dropped) and the real live NC row, each with its own real CDN photo PLUS a
# relative-path icon (the wishlist heart) that must never be mistaken for one.
_WW_CARDS_HTML = """
<div class="panel panel-default hasQuickbid clearfix listing">
    <div class="row" data-listingid="8064083">
        <div class="col-xs-12 col-sm-4 img-container listImg">
            <a href="/Event/LotDetails/5064083/1742-South-28th-St-Clarksburg-WV-26301-403005">
                <img src="https://auctionnetworkimages.blob.core.windows.net/assets/media/aaaa_fullsize.jpg" alt="Listing Image" class="img-responsive" />
            </a>
        </div>
        <div class="col-xs-12 col-sm-5 list-content">
            <div class="wishlisti_box"><img src="Content/Images/wheart.png" /></div>
            <div class="centerAboveContent">
                <h1 class="title inlinebidding">
                    <a href="/Event/LotDetails/5064083/1742-South-28th-St-Clarksburg-WV-26301-403005">
                    1742 South 28th St <br />
                    Clarksburg, WV 26301
                    </a>
                </h1>
            </div>
        </div>
    </div>
</div>
<div class="panel panel-default hasQuickbid clearfix listing">
    <div class="row" data-listingid="8236105">
        <div class="col-xs-12 col-sm-4 img-container listImg">
            <a href="/Event/LotDetails/2255089/825-Sunset-Dr-Laurinburg-NC-28352-400905">
                <img src="https://auctionnetworkimages.blob.core.windows.net/assets/media/fcd8eb9b_fullsize.jpg" alt="Listing Image" class="img-responsive" />
            </a>
        </div>
        <div class="col-xs-12 col-sm-5 list-content">
            <div class="wishlisti_box">
                <a href="/Listing/AddWatch/8236105"><img src="Content/Images/wheart.png" /></a>
            </div>
            <div class="centerAboveContent">
                <h1 class="title inlinebidding">
                    <a href="/Event/LotDetails/2255089/825-Sunset-Dr-Laurinburg-NC-28352-400905">
                    825 Sunset Dr <br />
                    Laurinburg, NC 28352
                    </a>
                </h1>
                <div class="propFeaturesRow">
                    <div class="bedBathDivParent">
                        <img class="iconbedbath" src="Content/Images/double-bed.png" />
                        <div class="bedBathDiv">2 Beds</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
"""

# One Founders FCU card: an orbit carousel with 2 real /_s3/ gallery photos
# (the first repeated, matching the live page's thumbnail-strip duplication)
# plus a camera.png placeholder and a themed NCUA seal that must not leak in.
_FOUNDERS_CARD_HTML = """
<div class="repo foreclosure">
  <div class="grid-x">
    <div class="medium-6 cell repo-image">
      <div class="orbit" aria-label="Repo images of 2755 US Hwy 74, Wadesboro, NC">
        <ul class="orbit-container">
          <li class="orbit-slide"><figure class="orbit-figure"><div class="media-image">
            <img loading="lazy" src="/_s3/foundersfcu-com/files/image/ext1.webp?VersionId=abc" width="960" height="1280" alt="exterior1" class="img-fluid" />
          </div></figure></li>
          <li class="orbit-slide"><figure class="orbit-figure"><div class="media-image">
            <img loading="lazy" src="/_s3/foundersfcu-com/files/image/ext2.webp?VersionId=def" width="960" height="1280" alt="exterior2" class="img-fluid" />
          </div></figure></li>
        </ul>
        <img src="/sites/default/themes/foundersfcu/images/camera.png" alt="" />
        <img src="/_s3/foundersfcu-com/files/image/ext1.webp?VersionId=abc" width="960" height="1280" alt="exterior1" class="img-fluid" />
      </div>
    </div>
    <div class="medium-6 cell">
      <p>Property sold "As-Is"</p>
      <p>2755 US Hwy 74, Wadesboro, NC</p>
      <p>Price:</p><p>$160,000</p>
      <p>Address:</p><p>2755 US Hwy 74 E, Wadesboro, NC 28170</p>
      <img src="/sites/default/themes/foundersfcu/images/logo/ncua-large.png" alt="NCUA logo" />
    </div>
  </div>
</div>
"""


def test_ww_card_parser_keeps_only_the_footprint_row():
    rows = _parse_cards(_WW_CARDS_HTML, "national.auction_bank_reo.williams_williams",
                        "https://www.williamsauction.com/", ListingType.AUCTION,
                        card_selector=_WW_CARD_SELECTOR, image_base="https://bid.auctionnetwork.com",
                        detail_selector=_WW_DETAIL_SELECTOR,
                        detail_base="https://bid.auctionnetwork.com", want_price=False)
    assert len(rows) == 1
    assert rows[0].street_address == "825 Sunset Dr"
    assert rows[0].city == "Laurinburg" and rows[0].state == "NC"


def test_ww_card_parser_pairs_each_cards_own_photo():
    rows = _parse_cards(_WW_CARDS_HTML, "s", "https://www.williamsauction.com/",
                        ListingType.AUCTION, card_selector=_WW_CARD_SELECTOR,
                        image_base="https://bid.auctionnetwork.com",
                        detail_selector=_WW_DETAIL_SELECTOR,
                        detail_base="https://bid.auctionnetwork.com", want_price=False)
    photos = rows[0].raw["images"]["real"]
    assert photos == [
        "https://auctionnetworkimages.blob.core.windows.net/assets/media/fcd8eb9b_fullsize.jpg"
    ]
    # the WV card's own photo (dropped with the row) must never appear here
    assert "aaaa_fullsize.jpg" not in photos[0]


def test_ww_card_parser_builds_the_real_per_listing_detail_url():
    rows = _parse_cards(_WW_CARDS_HTML, "s", "https://www.williamsauction.com/",
                        ListingType.AUCTION, card_selector=_WW_CARD_SELECTOR,
                        image_base="https://bid.auctionnetwork.com",
                        detail_selector=_WW_DETAIL_SELECTOR,
                        detail_base="https://bid.auctionnetwork.com", want_price=False)
    assert rows[0].source_url == (
        "https://bid.auctionnetwork.com/Event/LotDetails/2255089/"
        "825-Sunset-Dr-Laurinburg-NC-28352-400905"
    )


def test_real_image_urls_excludes_relative_icon_paths():
    """The wishlist heart and bed/bath icons are bare 'Content/Images/...'
    paths with no scheme and no leading slash -- never allowed through."""
    from selectolax.parser import HTMLParser

    card = HTMLParser(_WW_CARDS_HTML).css("div.row[data-listingid]")[1]
    urls = _real_image_urls(card, base="https://bid.auctionnetwork.com")
    assert urls == [
        "https://auctionnetworkimages.blob.core.windows.net/assets/media/fcd8eb9b_fullsize.jpg"
    ]
    assert not any("Content/Images" in u for u in urls)


def test_founders_card_parser_wires_all_gallery_photos_deduplicated():
    rows = _parse_cards(_FOUNDERS_CARD_HTML, "national.auction_bank_reo.founders_fcu",
                        "https://www.foundersfcu.com/foreclosures", ListingType.REO,
                        card_selector=_FOUNDERS_CARD_SELECTOR,
                        image_base="https://www.foundersfcu.com",
                        allow_relative_image_prefix="/_s3/", want_price=True)
    assert len(rows) == 1
    photos = rows[0].raw["images"]["real"]
    # de-duplicated (ext1 appears twice in the live markup: carousel + thumb strip)
    assert len(photos) == 2
    assert all(p.startswith("https://www.foundersfcu.com/_s3/") for p in photos)
    assert rows[0].street_address == "2755 US Hwy 74 E"
    assert rows[0].raw["auction_bank_reo"]["price"] == 160000.0


def test_founders_card_parser_excludes_theme_icons_and_seals():
    from selectolax.parser import HTMLParser

    card = HTMLParser(_FOUNDERS_CARD_HTML).css_first("div.repo.foreclosure")
    urls = _real_image_urls(card, base="https://www.foundersfcu.com",
                            allow_relative_prefix="/_s3/")
    assert not any("camera.png" in u or "ncua-large.png" in u for u in urls)


def test_card_parser_returns_empty_on_a_selector_miss_not_a_crash():
    """A future markup change (selector no longer matches) must degrade
    gracefully to [] so callers fall back to parse_properties(), never raise."""
    assert _parse_cards("<html><body>no cards here</body></html>", "s", "u",
                        ListingType.AUCTION, card_selector=_WW_CARD_SELECTOR,
                        image_base="https://bid.auctionnetwork.com") == []
    assert _parse_cards("not even html", "s", "u", ListingType.AUCTION,
                        card_selector=_WW_CARD_SELECTOR,
                        image_base="https://bid.auctionnetwork.com") == []
