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
from foreclosure_scraper.scrapers.national.freddie_homesteps import (
    _decode_cfemail,
    _parse_detail_page,
    _parse_row,
)
from foreclosure_scraper.web_artifact import _slim_raw

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


# ---------------------------------------------------------------------------
# Per-listing detail page (2026-10-04, batch 16): the card never carries a
# county at all -- a national/REO row with no county gets dropped outright
# by main._countyless_national(), so this is a real board-reach bug, not
# cosmetic. The detail page also has 4 more photos, precise lat/lng, and a
# real listing-agent name/phone/email (Cloudflare-obfuscated in the raw
# HTML but a plain single-byte-XOR decode, the same one the page's own JS
# runs client-side -- no login/bypass involved).
# ---------------------------------------------------------------------------

# A trimmed but real detail page, captured live 2026-10-04 against
# https://www.homesteps.com/listingdetails/2005-ada-williams-ln-lenoir-nc-28645
_REAL_DETAIL_HTML = """
<html><body>
<script>
const propertyData = {
  propertyLatLng: {
    lat: 35.937209,
    lng: -81.613939
  }
};
</script>
<img src="https://rbimages.blob.core.windows.net/rb-images/US/real-estate/mls-homes/single-family-property/for-sale/NC/Lenoir/28645/1774-CAR4425402-20260916-2005-Ada-Williams-Lane-1.jpg">
<img src="https://rbimages.blob.core.windows.net/rb-images/US/real-estate/mls-homes/single-family-property/for-sale/NC/Lenoir/28645/1774-CAR4425402-20260916-2005-Ada-Williams-Lane-2.jpg">
<img src="https://rbimages.blob.core.windows.net/rb-images/US/real-estate/mls-homes/single-family-property/for-sale/NC/Lenoir/28645/1774-CAR4425402-20260916-2005-Ada-Williams-Lane-3.jpg">
<ul class="detail-list two-col">
  <li><span>Price:</span><strong>$189,900</strong></li>
  <li><span>Bedrooms:</span><strong>2</strong></li>
  <li><span>Year Built:</span><strong>1988</strong></li>
  <li><span>Lot Size:</span><strong>1.1 acres</strong></li>
  <li><span>Subdivision:</span><strong>None</strong></li>
</ul>
<ul class="detail-list">
  <li><span>County:</span><strong>CALDWELL</strong></li>
  <li><span>Property Type:</span><strong>Single-Family</strong></li>
</ul>
<div class="cell large-4">
  <div class="callout background-navy">
    <h2>Agent Information</h2>
    <p>Damion  Patton <br>
      Dana Pattonson <br>
      Phone:
      (828) 555-0877
    </p>
    <a class="button mailto-agent" href="/cdn-cgi/l/email-protection#593a36372d383a2d696d192a383429353c7434383035772d3c2a2d">Email Agent</a>
  </div>
</div>
</body></html>
"""


def test_decode_cfemail_matches_the_real_page_js():
    """Verified live against the actual decoded value homesteps.com's own
    client-side JS renders for this exact obfuscated string."""
    hexstr = "593a36372d383a2d696d192a383429353c7434383035772d3c2a2d"
    assert _decode_cfemail(hexstr) == "contact04@sample-mail.test"


def test_decode_cfemail_garbage_input_returns_none():
    assert _decode_cfemail("") is None
    assert _decode_cfemail("not-hex-at-all") is None


def test_parse_detail_page_extracts_county_specs_latlng_and_agent():
    detail = _parse_detail_page(_REAL_DETAIL_HTML)
    assert detail["county"] == "Caldwell"
    assert detail["year_built"] == 1988
    assert detail["acreage"] == 1.1
    assert detail["latitude"] == 35.937209
    assert detail["longitude"] == -81.613939
    assert detail["agent"]["name"] == "Damion  Patton"
    assert detail["agent"]["phone"] == "(828) 555-0877"
    assert detail["agent"]["email"] == "contact04@sample-mail.test"
    assert detail["specs"]["county"] == "CALDWELL"  # raw, pre-.title() value kept too


def test_parse_detail_page_captures_the_full_gallery_not_just_the_teaser_photo():
    """The card/JSON-LD teaser only ever surfaces the FIRST image -- this
    page has 3 (the real one has 5); all must be captured, not just one."""
    detail = _parse_detail_page(_REAL_DETAIL_HTML)
    assert len(detail["photos"]) == 3
    assert detail["photos"][0].endswith("Lane-1.jpg")
    assert detail["photos"][2].endswith("Lane-3.jpg")


def test_parse_detail_page_missing_sections_degrade_gracefully():
    detail = _parse_detail_page("<html><body><p>nothing here</p></body></html>")
    assert detail["county"] is None
    assert detail["photos"] == []
    assert detail["agent"] == {}


class TestRawKeepRegression:
    """A SECOND instance of the exact bug this project's extraction-gaps
    audit keeps finding, in the SAME scraper: homesteps_details and
    homesteps_img_kind_slug (added 2026-10-01, alongside homesteps_kind)
    were never registered in RAW_KEEP either -- only homesteps_kind was.
    Confirmed via a direct _slim_raw() round-trip."""

    def test_all_four_homesteps_flat_keys_now_survive_slim_raw(self):
        raw = {
            "homesteps_kind": "Single-Family",
            "homesteps_details": "2 beds, 2 baths, 1,296 sq. ft.",
            "homesteps_img_kind_slug": "single-family-property",
            "homesteps_agent": {"name": "Dana Pattonson", "phone": "(828) 555-0877"},
            "homesteps_specs": {"year built": "1988"},
            "images": {"real": ["https://rbimages.blob.core.windows.net/x.jpg"]},
        }
        sliced = _slim_raw(raw)
        assert sliced == raw, (
            f"RAW_KEEP dropped: {sorted(set(raw) - set(sliced))}"
        )
