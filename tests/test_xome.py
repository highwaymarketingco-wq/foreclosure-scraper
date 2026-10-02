"""xome.py was rewritten 2026-10-01 (national-auction-tier audit, batch 4)
after the site was redesigned: the old URLs (/auctions/bank-owned,
/auctions/foreclosure-homes) now 301-redirect to a query-flag form
(/auctions?bank-owned), the third old URL (/auctions/foreclosuresales) is
now a dead/empty category, pagination moved from a JS "click next, cards
accumulate" control to a plain &page=N param, and the card markup changed
completely (data-testid="auction-property-card-container" per card instead
of the old #streetAddress-{id} id-per-field spans).

Most importantly: confirmed live that a PLAIN GET (no Scrapling, no
headless browser) already returns every card's full field set in the raw
server HTML, so the whole stealth-browser + click-pagination approach was
replaced with fast plain fetches -- `requires_render` is now False."""
from selectolax.parser import HTMLParser

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national.xome import _parse_card

_SLUG = "national.xome"


def _card(html: str):
    tree = HTMLParser(f'<div class="grid">{html}</div>')
    return tree.css_first('[data-testid="auction-property-card-container"]')


# Trimmed, live-captured card shape (2026-10-01).
_SC_CARD = """
<div data-testid="auction-property-card-container">
  <a href="/auctions/252-friendship-road-seneca-sc-29678-424123456"></a>
  <div data-testid="property-card-amt"><p>$125,000</p></div>
  <div data-testid="property-card-beds-and-bath">
    <p><span class="detailBold">3</span> Beds &middot; <span class="detailBold">1</span> Baths &middot; <span class="detailBold">1,794</span> Sq. Ft.</p>
  </div>
  <span class="transactionText">Bank Owned</span>
  <span class="timelineDate">Oct 03 - 07</span>
  <span class="primaryBoldText">Marketing</span>
  <div data-testid="property-card-bid-type">Starting Bid</div>
  <div class="flagChipContent">Financing Available</div>
  <div class="flagChipContent">Interior Access Available</div>
  <div class="flagChipContent">Financing Available</div>
  <div class="addressLine1">252 Friendship Road</div>
  <div class="addressLine2">Seneca, SC 29678</div>
</div>
"""

_TBD_CARD = _SC_CARD.replace("<p>$125,000</p>", "<p>TBD</p>")

_OUT_OF_STATE_CARD = _SC_CARD.replace("Seneca, SC 29678", "Monticello, KY 42633").replace(
    "252 Friendship Road", "30 Jenkins St"
)

_NO_ADDRESS_CARD = """
<div data-testid="auction-property-card-container">
  <a href="/auctions/some-slug-sc-29678-999"></a>
  <div data-testid="property-card-amt"><p>$1,000</p></div>
</div>
"""


def test_real_sc_card_parses_all_fields():
    li = _parse_card(_card(_SC_CARD), _SLUG)
    assert li is not None
    assert li.state == "SC"
    assert li.city == "Seneca"
    assert li.zip_code == "29678"
    assert li.street_address == "252 Friendship Road"
    assert li.county == "Oconee"
    assert li.opening_bid == 125000.0
    assert li.bedrooms == 3.0
    assert li.bathrooms == 1.0
    assert li.living_sqft == 1794.0
    assert li.listing_type == ListingType.REO
    assert li.case_number == "xome-424123456"
    assert li.source_url == "https://www.xome.com/auctions/252-friendship-road-seneca-sc-29678-424123456"


def test_tbd_price_is_not_a_fabricated_zero_or_number():
    li = _parse_card(_card(_TBD_CARD), _SLUG)
    assert li is not None
    assert li.opening_bid is None


def test_out_of_core_state_is_dropped():
    assert _parse_card(_card(_OUT_OF_STATE_CARD), _SLUG) is None


def test_card_without_address_is_dropped_not_fabricated():
    assert _parse_card(_card(_NO_ADDRESS_CARD), _SLUG) is None


def test_duplicate_flag_chips_are_deduplicated():
    """Regression pin: the live markup repeats a flag chip (an overflow
    "+1 More" duplicate rendering) -- must not double-count it."""
    li = _parse_card(_card(_SC_CARD), _SLUG)
    assert li.raw["xome"]["flags"] == ["Financing Available", "Interior Access Available"]


def test_county_resolves_via_shared_gazetteer():
    li = _parse_card(_card(_SC_CARD), _SLUG)
    assert li.county == "Oconee"
