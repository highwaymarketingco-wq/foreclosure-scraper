"""gsa_surplus.py was rewritten 2026-09-15: the old target URL 404s and its
extraction was a loose regex over whatever blocks matched. The real page is
a clean USWDS card list with a per-card data-state attribute; verify the
parser reads real cards correctly, skips out-of-footprint states, and
drops closed deals."""
from selectolax.parser import HTMLParser

from foreclosure_scraper.scrapers.national.gsa_surplus import _parse_card


def _card(html: str):
    tree = HTMLParser(f'<ul>{html}</ul>')
    return tree.css_first("li.usa-card")


_REAL_SC_CARD = """
<li class="usa-card js-filterable" data-area='"1"' data-state='"SC"' data-type='["Office" , "Courthouse"]'>
  <div class="usa-card__container">
    <div class="usa-card__header"><h3 class="usa-card__heading">G. ROSS ANDERSON JR. FEDERAL BUILDING AND COURTHOUSE</h3></div>
    <div class="usa-card__media usa-card__media--exdent"><div class="usa-card__img"><img src="https://www.gsa.gov/system/files/Disposition-G_Ross_CH_final.jpg" alt="" class=" img-responsive"></div></div>
    <div class="usa-card__body">
      <p><a class="usa-link--external" href="https://maps.app.goo.gl/GmwCmYwA5LGsQnmM8">315 S. McDuffie St, Anderson, SC 29624</a></p>
      <p class="margin-top-1">Type: <strong>Office, Courthouse</strong><br>Rentable Area: <strong>28,567 ft<sup>2</sup></strong></p>
      <ul class="usa-collection__meta"><li class="usa-collection__meta-item usa-tag bg-base-darker text-white">Date listed: 9/10/2026</li></ul>
    </div>
  </div>
</li>
"""

_SOLD_CARD = """
<li class="usa-card js-filterable" data-area='"2"' data-state='"SC"' data-type='"Courthouse"'>
  <div class="usa-card__container">
    <div class="usa-card__header"><h3 class="usa-card__heading">SOLD BUILDING</h3></div>
    <div class="usa-card__body">
      <p><a class="usa-link--external" href="https://maps.app.goo.gl/x">1 Main St, Columbia, SC 29201</a></p>
      <p class="margin-top-1">Type: <strong>Office</strong><br>Rentable Area: <strong>1,000 ft<sup>2</sup></strong></p>
      <ul class="usa-collection__meta">
        <li class="usa-collection__meta-item usa-tag bg-base-darker text-white">Date listed: 4/17/2025</li>
        <li class="usa-collection__meta-item usa-tag bg-red text-white">SOLD</li>
      </ul>
    </div>
  </div>
</li>
"""

_TX_CARD = """
<li class="usa-card js-filterable" data-area='"1"' data-state='"TX"' data-type='"Office"'>
  <div class="usa-card__container">
    <div class="usa-card__header"><h3 class="usa-card__heading">TEXAS BUILDING</h3></div>
    <div class="usa-card__body">
      <p><a class="usa-link--external" href="https://maps.app.goo.gl/y">1 Main St, Fort Worth, TX 76102</a></p>
      <p class="margin-top-1">Type: <strong>Office</strong><br>Rentable Area: <strong>1,000 ft<sup>2</sup></strong></p>
      <ul class="usa-collection__meta"><li class="usa-collection__meta-item usa-tag bg-base-darker text-white">Date listed: 9/10/2026</li></ul>
    </div>
  </div>
</li>
"""


def test_real_sc_card_parses_correctly():
    li = _parse_card(_card(_REAL_SC_CARD), "https://gsa.gov/x")
    assert li is not None
    assert li.state == "SC"
    assert li.city == "Anderson"
    assert li.zip_code == "29624"
    assert li.street_address == "315 S. McDuffie St"
    assert li.living_sqft == 28567.0
    assert li.sale_date is None


def test_sold_card_is_dropped():
    assert _parse_card(_card(_SOLD_CARD), "https://gsa.gov/x") is None


def test_out_of_footprint_state_is_dropped():
    assert _parse_card(_card(_TX_CARD), "https://gsa.gov/x") is None


def test_card_photo_is_captured():
    """FIXED 2026-10-01: every card carries a real listing photo
    (usa-card__img > img) that was never captured."""
    li = _parse_card(_card(_REAL_SC_CARD), "https://gsa.gov/x")
    assert li.raw["images"]["real"] == [
        "https://www.gsa.gov/system/files/Disposition-G_Ross_CH_final.jpg"
    ]


def test_card_without_photo_sets_no_images_key():
    assert _parse_card(_card(_SOLD_CARD), "https://gsa.gov/x") is None  # closed, N/A
    li = _parse_card(_card(_TX_CARD), "https://gsa.gov/x")
    assert li is None  # out of footprint, N/A -- use a minimal in-footprint, photo-less card
    minimal = """
    <li class="usa-card js-filterable" data-area='"1"' data-state='"SC"' data-type='"Office"'>
      <div class="usa-card__container">
        <div class="usa-card__header"><h3 class="usa-card__heading">X</h3></div>
        <div class="usa-card__body">
          <p><a class="usa-link--external" href="https://maps.app.goo.gl/x">1 Main St, Anderson, SC 29621</a></p>
        </div>
      </div>
    </li>
    """
    li2 = _parse_card(_card(minimal), "https://gsa.gov/x")
    assert li2 is not None
    assert li2.raw.get("images") == {}


def test_county_resolves_via_gazetteer():
    """FIXED 2026-10-01: a card never states its own county -- Anderson, SC
    is a known in-footprint city in the shared WNC/upstate-SC gazetteer."""
    li = _parse_card(_card(_REAL_SC_CARD), "https://gsa.gov/x")
    assert li.county == "Anderson"
