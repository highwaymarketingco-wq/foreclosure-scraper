"""national.freddie_homesteps: 2026-10-01 national/reo per-source extraction
audit.

Live-verified three gaps against the current homesteps.com markup:
1. The card's real listing photo (div.property-image img) was never
   captured, even though it is present on every row that has one --
   same miss class fixed today in national.gsa_surplus / servicelink_auction
   / tranzon_auctions / national.hubzu (raw["images"] = {"real": [...]}).
2. The property-type badge this scraper's kind_node selector originally
   targeted is gone from the live markup (confirmed live: 0/26 NC+SC rows
   matched it, so property_kind was UNKNOWN on every single row) -- a site
   redesign. The MLS photo filename still encodes the type
   ("mls-homes/single-family-property/...", "mobile-manufactured-property",
   "condo-property", ...), used here as a fallback.
3. "2 beds, 2 baths, 1,296 sq. ft." was kept only as free text inside
   description, never parsed into the Listing's own bedrooms/bathrooms/
   living_sqft fields.

"no_photos.svg" is the site's own generic no-photo placeholder (confirmed
live on several SC rows) and must not be reported as a real image.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.national.freddie_homesteps import _parse_row

# A trimmed but real card, captured live 2026-10-01 against
# https://www.homesteps.com/listing/search?search=NC
_REAL_CARD_HTML = """
<div class="property-teaser grid-x grid-padding-x background-white">
  <div class="property-image cell small-12 medium-4">
    <img src="https://rbimages.blob.core.windows.net/rb-images/US/real-estate/mls-homes/single-family-property/for-sale/NC/Lenoir/28645/1774-CAR4425402-20260916-2005-Ada-Williams-Lane-1.jpg" alt="" style="">
  </div>
  <div class="cell small-12 medium-8">
    <div class="property-status status-active">
      <span class="property-status-value weight-medium">Active</span>
    </div>
    <div class="property-price weight-medium">$189,900</div>
    <div class="property-details">2 beds, 2 baths, 1,296 sq. ft.</div>
    <div class="property-address">
      2005 Ada Williams Ln,
      Lenoir,
      NC
      28645
    </div>
  </div>
</div>
"""

_NO_PHOTO_CARD_HTML = """
<div class="property-teaser grid-x grid-padding-x background-white">
  <div class="property-image cell small-12 medium-4">
    <img src="/g/files/ynjofi196/themes/site/hs_theme/images/no_photos.svg" alt="" style="">
  </div>
  <div class="cell small-12 medium-8">
    <div class="property-price weight-medium">$99,900</div>
    <div class="property-details">3 beds, 1 baths, 1,100 sq. ft.</div>
    <div class="property-address">
      100 Main St,
      Columbia,
      SC
      29170
    </div>
  </div>
</div>
"""


def _row(html: str):
    return HTMLParser(html).css_first("div.property-teaser")


def test_real_card_captures_photo_kind_and_bbs():
    li = _parse_row(_row(_REAL_CARD_HTML), "NC")
    assert li is not None
    assert li.raw["images"] == {
        "real": ["https://rbimages.blob.core.windows.net/rb-images/US/real-estate/"
                 "mls-homes/single-family-property/for-sale/NC/Lenoir/28645/"
                 "1774-CAR4425402-20260916-2005-Ada-Williams-Lane-1.jpg"]
    }
    assert li.property_kind == PropertyKind.SINGLE_FAMILY
    assert li.bedrooms == 2
    assert li.bathrooms == 2
    assert li.living_sqft == 1296
    assert li.street_address == "2005 Ada Williams Ln"
    assert li.opening_bid == 189900.0


def test_no_photos_svg_placeholder_is_not_a_real_image():
    li = _parse_row(_row(_NO_PHOTO_CARD_HTML), "SC")
    assert li is not None
    assert "images" not in li.raw
    # No MLS-feed slug on this card either, so kind falls back to UNKNOWN --
    # better than a wrong guess.
    assert li.property_kind == PropertyKind.UNKNOWN
    assert li.bedrooms == 3
    assert li.bathrooms == 1
    assert li.living_sqft == 1100
