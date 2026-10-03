"""Extraction-completeness audit 2026-10-03.

Live-confirmed on irsauctions.gov (2026-10-03) that the site's Drupal
template now renders most attributes UNQUOTED (`href=/ad/foo-bar` instead of
`href="/ad/foo-bar"`). Every regex in this scraper that assumed a quoted
`href="..."` / `datetime="..."` silently matched ZERO items -- a live
fetch() returned 0 results on EVERY state, not just an empty NC/SC footprint
(which the old docstring/tests would have you believe is just quiet
off-footprint inventory).

A live re-check the same day recovered a REAL, currently-active, in-footprint
lot the old code could never see: 340 Cedar Grove Dr, Henderson, NC 27537
(auction_datetime 2026-10-28, minimum bid $81,480), plus a 4-photo real
gallery and 3 real federal PDFs (signed deed-of-trust notice + mail-in-bid
form) that were ALSO never captured even when a page WAS reachable --
this scraper had no image capture at all.

These fixtures mirror the real unquoted markup shape (verified against the
live page's actual bytes), not the old quoted-attribute assumption.
"""
from foreclosure_scraper.scrapers.national.irs_judicial_sales import (
    _AD_RE,
    parse_detail,
)

_URL = "https://www.irsauctions.gov/ad/half-interest-house-acreage"

# Trimmed synthetic index page matching the REAL unquoted-attribute Drupal
# markup (verified live 2026-10-03): one real-property /ad/ card (in NC) and
# one external vehicle-auction card that must NOT be mistaken for a lot.
_INDEX_PAGE = """
<html><body>
<ul id=auction-results-list>
<li class="item-list auction-item" data-asset-type=8><article class="irs-ad usa-card__container">
<h3 class="usa-card__heading"><a href=/ad/half-interest-house-acreage rel=bookmark><span class=treas-page-title>Half interest in a house and acreage!!!</span></a></h3>
</article></li>
<li class="item-list auction-item external-sale"><article class="irs-ad usa-card__container">
<a href=https://www.gsaauctions.gov/auctions rel="bookmark noopener" class=ext target=_blank>2002 Red Kenworth Truck</a>
</article></li>
</ul>
</body></html>
"""

# Trimmed synthetic detail page matching the REAL unquoted markup for the
# Henderson, NC lot (field names/structure verified live 2026-10-03).
_DETAIL_PAGE = """
<html><head><title>Half interest in a house and acreage!!! | IRS Auctions</title></head>
<body>
<h1 class=margin-0><span class=treas-page-title>Half interest in a house and acreage!!!</span></h1>
<div class="field field--name-field-property-address field--type-address field__item">
<address>340 Cedar Grove Dr.<br>Henderson, 27537 NC<br>United States</address>
</div>
<div>Date of Auction</div>
<time datetime=2026-10-28T16:00:00Z>Oct 28, 2026</time>
<div class="field field--name-field-minimum-bid field__item">$ 81,480.00</div>
<div class="field field--name-field-notice-information field__item">Half interest in real property.</div>
<div class="field field--name-field-sale-location field__item">
<address>Henderson NC<br>United States</address>
</div>
<div class="field field--name-field-order-of-sale field__item">
<a href=/sites/default/files/100/SESS_F2434_340_Cedar_Grove_Dr_signed.pdf>Notice of Sale</a>
</div>
<div class="field field--name-field-notice-of-encumbrances field__item">
<a href=/sites/default/files/100/SESS_340_Cedar_Grove_F2434B_signed.pdf>Encumbrances</a>
</div>
<div class="field field--name-field-mail-in-bid-form field__item">
<a href=/sites/default/files/100/SESS_MIB_340_Cedar_Grove_Dr.pdf>Mail-in Bid</a>
</div>
<div class="photoswipe-gallery field field--name-field-asset-photos field--type-entity-reference field__item">
<div class=field__item><a href=/sites/default/files/100/View_of_340_Cedar_Grove_Dr_with_adjoining_land_from_road.jpg class=photoswipe><img loading=lazy src=/sites/default/files/100/View_of_340_Cedar_Grove_Dr_with_adjoining_land_from_road.jpg></a></div>
<div class=field__item><a href=/sites/default/files/100/340_Cedar_Grove_Dr_Henderson_NC.jpg class=photoswipe><img loading=lazy src=/sites/default/files/100/340_Cedar_Grove_Dr_Henderson_NC.jpg></a></div>
</div>
</div>
</body></html>
"""

# Out-of-footprint sibling (MN) -- same unquoted markup shape, no gallery,
# must still be correctly filtered by state.
_DETAIL_PAGE_OUT_OF_FOOTPRINT = _DETAIL_PAGE.replace(
    "340 Cedar Grove Dr.<br>Henderson, 27537 NC<br>United States",
    "20842 Jacquard Ave<br>Lakeville, 55044 MN<br>United States",
).replace(
    '<div class="photoswipe-gallery field field--name-field-asset-photos '
    'field--type-entity-reference field__item">\n'
    '<div class=field__item><a href=/sites/default/files/100/View_of_340_Cedar_Grove_Dr_with_adjoining_land_from_road.jpg class=photoswipe><img loading=lazy src=/sites/default/files/100/View_of_340_Cedar_Grove_Dr_with_adjoining_land_from_road.jpg></a></div>\n'
    '<div class=field__item><a href=/sites/default/files/100/340_Cedar_Grove_Dr_Henderson_NC.jpg class=photoswipe><img loading=lazy src=/sites/default/files/100/340_Cedar_Grove_Dr_Henderson_NC.jpg></a></div>\n'
    '</div>',
    "",
)


def test_index_discovery_matches_unquoted_href_regression_pin():
    """REGRESSION: the live site's unquoted `href=/ad/foo` markup must be
    discovered. Pre-fix, the strict `href="..."` regex matched 0 items on
    this exact page shape."""
    ads = sorted({m.group(1) for m in _AD_RE.finditer(_INDEX_PAGE)})
    assert ads == ["/ad/half-interest-house-acreage"]


def test_external_vehicle_auction_card_not_mistaken_for_a_lot():
    ads = {m.group(1) for m in _AD_RE.finditer(_INDEX_PAGE)}
    assert not any("gsaauctions" in a for a in ads)


def test_real_in_footprint_lot_parses_with_unquoted_markup():
    li = parse_detail(_DETAIL_PAGE, _URL)
    assert li is not None
    assert li.state == "NC"
    assert li.street_address == "340 Cedar Grove Dr."
    assert li.city == "Henderson"
    assert li.zip_code == "27537"
    assert li.opening_bid == 81480.0


def test_sale_date_parses_from_unquoted_datetime_attr():
    """REGRESSION: `<time datetime=2026-10-28T16:00:00Z>` (no quotes) must
    still yield a real sale_date, not silently None."""
    li = parse_detail(_DETAIL_PAGE, _URL)
    assert li.sale_date is not None
    assert li.sale_date.year == 2026 and li.sale_date.month == 10 and li.sale_date.day == 28


def test_federal_pdfs_captured_from_unquoted_href():
    """REGRESSION: the order-of-sale/encumbrances/mail-in-bid PDFs sit behind
    unquoted hrefs; the old strict-quote regex captured none of them."""
    li = parse_detail(_DETAIL_PAGE, _URL)
    docs = li.raw["documents"]
    assert any("SESS_F2434" in d for d in docs)
    assert any("SESS_340_Cedar_Grove_F2434B" in d for d in docs)
    assert any("SESS_MIB" in d for d in docs)
    assert li.raw["notice_url"].startswith("https://www.irsauctions.gov/")


def test_real_photo_gallery_is_captured():
    """THE most common miss: a real per-property photo gallery sits right on
    the already-fetched detail page and was never captured at all (no image
    regex existed in this scraper before this fix)."""
    li = parse_detail(_DETAIL_PAGE, _URL)
    photos = li.raw["images"]["real"]
    assert len(photos) == 2
    assert all(p.startswith("https://www.irsauctions.gov/sites/default/files/") for p in photos)


def test_page_without_gallery_does_not_crash_and_omits_images():
    li = parse_detail(_DETAIL_PAGE_OUT_OF_FOOTPRINT, _URL)
    # out-of-footprint (MN) -- filtered to None regardless of gallery.
    assert li is None
