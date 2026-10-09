"""national.hud_homestore — extraction-completeness audit (batch 16, 2026-10-04).

Two real bugs confirmed live against hudhomestore.gov:

1. A `_slim_raw()` round-trip showed 9 of this scraper's 11 raw keys
   (fha_financing/listing_period/property_status/bid_open_date/
   period_deadline_date/bedrooms/bathrooms/sqft/year_built) were flat
   top-level keys never registered in web_artifact.RAW_KEEP -- silently
   dropped at every publish since this scraper was built. bedrooms/
   bathrooms/sqft/year_built are now promoted to first-class Listing
   fields; the rest moved under a new RAW_KEEP-registered
   raw["hud_homestore"] key.
2. Every case's own `/propertydetails?caseNumber=` page (confirmed live,
   no auth needed) carries a real "Listing Broker" name + phone + email,
   never fetched at all before this fix.
"""
from __future__ import annotations

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.national.hud_homestore import (
    _extract_broker,
    _to_listing,
)
from foreclosure_scraper.web_artifact import _slim_raw

# Mirrors the real searchresult row shape for case 387-044545 (confirmed
# live 2026-10-04 against the production POST /searchresult?handler=
# GetFilteredResult handler).
_REAL_SHAPE_ROW = {
    "propertyCaseNumber": "387-044545",
    "propertyCityStateZip": "Cashiers, NC, 28717",
    "propertyAddress": "29 Crystal Springs Trl",
    "propertyCity": "Cashiers",
    "propertyState": "NC",
    "propertyZip": "28717",
    "propertyCounty": "Jackson",
    "listPrice": "509000",
    "bedrooms": "2",
    "bathrooms": "2",
    "squareFootage": "1460",
    "yearBuilt": "1955",
    "fhaFinancing": "IN (Insured)",
    "listingPeriod": "Extended",
    "propertyStatus": "",
    "listDate": "08/20/2026",
    "periodDeadlineDate": "02/15/2027",
    "bidOpenDate": "10/05/2026",
    "latitude": "35.1021",
    "longitude": "-83.0957",
    "inAmenities": "Fireplace,",
    "outAmenities": "Patio/Deck,Porch,Fence,",
    "parkingType": "Driveway",
    "numberOfStories": "1.0",
    "propertyType": "Single Family Home",
    "galleryImages": '"1_(7)_587110_742969575.jpg","1_(1)_587110_359235140.jpg"',
    "bidderTypes": "Investor,Owner Occupant,Nonprofit,Government Agency,",
    "eligibleBidders": "All Bidders",
    "propertyThumb": (
        "https://res.cloudinary.com/yardi/image/upload/q_auto,f_auto,"
        "c_limit/d_hhs:themes:common:images:NoImage.jpg/hhs/"
        "1_(7)_587110_742969575.jpg"
    ),
}

# A compact synthetic /propertydetails page mirroring the REAL markup
# (class names + structure confirmed live 2026-10-04 against
# /propertydetails?caseNumber=387-044545) -- including the Asset Manager
# and Field Service Manager cards, which use the IDENTICAL shape, to prove
# the scoping-by-heading actually matters.
_REAL_SHAPE_DETAIL_HTML = """
<html><body>
<div class="row border-bottom mb-4 pb-4">
  <div class="col-12 d-flex align-items-start justify-content-left">
    <h2 class="h5 mb-3 font-weight-bold">Asset Manager</h2>
  </div>
  <div class="col-12 col-lg-4 d-flex flex-column">
    <div class="font-weight-bold">RAINE CUSTOMER SERVICE</div>
    <a href="/cdn-cgi/l/email-protection#x" title="CONTACT20@SAMPLE-MAIL.TEST">
      <span class="__cf_email__">[email&#160;protected]</span>
    </a>
    <div class="d-flex flex-row">
      <a href="tel:(555) 000-0000"><span class="sr-only">Asset Manager's Phone number</span><span>(555) 000-0000</span></a>
    </div>
  </div>
</div>
<div class="row border-bottom mb-4 pb-4">
  <div class="col-12 d-flex align-items-start justify-content-left">
    <h2 class="h5 mb-3 font-weight-bold">Listing Broker</h2>
    <button data-title="The Listing Broker was hired by the Asset Manager to assist with the marketing of the home.">info</button>
  </div>
  <div class="col-12 col-lg-4 d-flex flex-column align-items-start justify-content-start mb-2 mb-lg-0">
    <div class="font-weight-bold">COLE ADAMSTEST</div>
    <a href="/cdn-cgi/l/email-protection#0d2d4e4" class="truncate" title="CONTACT05@SAMPLE-MAIL.TEST">
      <span class="sr-only">Listing Broker's Email id</span>
      <span class="__cf_email__" data-cfemail="a0e3">[email&#160;protected]</span>
    </a>
    <div class="d-flex flex-row">
      <a href="tel:(828) 555-0682">
        <span class="sr-only">Listing Broker's Phone number</span>
        <span>(828) 555-0682</span>
      </a>
      <div class="text-muted ml-2" aria-hidden="true">phone</div>
    </div>
  </div>
  <div class="col-12 col-lg-4 d-flex flex-column">
    <div class="font-weight-bold">SAGE REALTY LLC</div>
  </div>
</div>
<div class="row border-bottom mb-4 pb-4">
  <div class="col-12 d-flex align-items-start justify-content-left">
    <h2 class="h5 mb-3 font-weight-bold">Field Service Manager</h2>
  </div>
  <div class="col-12 col-lg-4 d-flex flex-column">
    <div class="font-weight-bold">EDDIE SAN TESTMAN</div>
    <a href="/cdn-cgi/l/email-protection#y" title="E.TESTMAN@SAMPLE-MAIL.TEST">
      <span class="__cf_email__">[email&#160;protected]</span>
    </a>
  </div>
</div>
</body></html>
"""


class TestRawKeepRegression:
    """The actual bug: _slim_raw() silently dropping unregistered flat
    scalar keys. This pins the fix so it can't regress unnoticed again."""

    def test_old_flat_keys_would_have_been_dropped(self):
        """Documents the ORIGINAL bug shape for posterity -- these flat
        top-level keys are NOT registered in RAW_KEEP (by design, they no
        longer exist in this scraper's raw output) and would vanish."""
        would_be_dropped = {
            "fha_financing": "IN (Insured)", "listing_period": "Extended",
            "property_status": "", "bid_open_date": "10/05/2026",
            "period_deadline_date": "02/15/2027", "bedrooms": 2,
            "bathrooms": 2.0, "year_built": 1955,
        }
        # The old shape also had a flat "sqft". RAW_KEEP has kept a flat "sqft" since 9d60dfe0
        # (2026-10-04) for national.foreclosure_dot_com, whose raw carries beds/baths/sqft, so
        # it is no longer dropped for any source. That does not touch this scraper's fix:
        # hud_homestore writes living_sqft and nests the rest under raw["hud_homestore"]
        # (see test_promoted_fields_are_first_class_and_need_no_registration below).
        assert _slim_raw({"sqft": 1460}) == {"sqft": 1460}
        out = _slim_raw(would_be_dropped)
        assert out == {}, (
            "if this ever starts keeping these flat keys, the fix's "
            "rationale (promote to first-class fields / nest under "
            "hud_homestore) should be revisited, not silently relied on"
        )

    def test_nested_hud_homestore_key_survives_slim_raw(self):
        li = _to_listing(_REAL_SHAPE_ROW, "NC")
        sliced = _slim_raw(li.raw)
        assert "hud_homestore" in sliced
        assert sliced["hud_homestore"]["fha_financing"] == "IN (Insured)"
        assert sliced["hud_homestore"]["listing_period"] == "Extended"
        assert sliced["hud_homestore"]["bid_open_date"] == "10/05/2026"

    def test_promoted_fields_are_first_class_and_need_no_registration(self):
        """bedrooms/bathrooms/living_sqft/year_built are now real Listing
        fields, which model_dump() always includes regardless of RAW_KEEP."""
        li = _to_listing(_REAL_SHAPE_ROW, "NC")
        assert li.bedrooms == 2
        assert li.bathrooms == 2.0
        assert li.living_sqft == 1460.0
        assert li.year_built == 1955


class TestListingBasics:
    def test_county_and_amenities_captured(self):
        li = _to_listing(_REAL_SHAPE_ROW, "NC")
        assert li.county == "Jackson"
        assert li.property_kind == PropertyKind.SINGLE_FAMILY
        hs = li.raw["hud_homestore"]
        assert hs["in_amenities"] == "Fireplace,"
        assert hs["out_amenities"] == "Patio/Deck,Porch,Fence,"
        assert hs["parking_type"] == "Driveway"
        assert hs["number_of_stories"] == 1.0
        assert hs["bidder_types"] == "Investor,Owner Occupant,Nonprofit,Government Agency,"
        assert hs["eligible_bidders"] == "All Bidders"

    def test_source_url_is_the_real_per_case_detail_page(self):
        """2026-06-19 claimed HUD has no stable public deep-link -- true
        only of the wrong path (/Listing/PropertyDetails, capital L, which
        404s). /propertydetails?caseNumber= is real and auth-free."""
        li = _to_listing(_REAL_SHAPE_ROW, "NC")
        assert li.source_url == "https://www.hudhomestore.gov/propertydetails?caseNumber=387-044545"

    def test_no_case_number_falls_back_to_the_search_page(self):
        row = dict(_REAL_SHAPE_ROW)
        row["propertyCaseNumber"] = ""
        li = _to_listing(row, "NC")
        assert li.source_url == "https://www.hudhomestore.gov/searchresult?stateCode=NC"


class TestBrokerExtraction:
    def test_scoped_to_listing_broker_not_asset_manager_or_field_service(self):
        """All three contact cards share IDENTICAL markup -- only the
        heading text differs. Must not pick up Asset Manager's or Field
        Service Manager's name/phone/email instead."""
        broker = _extract_broker(_REAL_SHAPE_DETAIL_HTML)
        assert broker["name"] == "COLE ADAMSTEST"
        assert broker["phone"] == "(828) 555-0682"
        assert broker["email"] == "CONTACT05@SAMPLE-MAIL.TEST"

    def test_phone_reads_the_tel_href_not_the_concatenated_link_text(self):
        """The <a href="tel:..."> wraps a visually-hidden sr-only span AND
        the visible number in a separate sibling span; .text() on the
        anchor concatenates BOTH with no separator ("Listing Broker's
        Phone number(828) 555-0682", confirmed live before this fix)."""
        broker = _extract_broker(_REAL_SHAPE_DETAIL_HTML)
        assert "Phone number" not in broker["phone"]
        assert broker["phone"] == "(828) 555-0682"

    def test_email_from_title_attribute_not_the_cloudflare_hex(self):
        """The Cloudflare-obfuscated __cf_email__ span is unreadable
        without a hex decode -- but the SAME <a>'s title attribute already
        carries the plain-text address, no decode needed."""
        broker = _extract_broker(_REAL_SHAPE_DETAIL_HTML)
        assert broker["email"] == "CONTACT05@SAMPLE-MAIL.TEST"

    def test_no_listing_broker_heading_returns_empty_dict(self):
        assert _extract_broker("<html><body><p>nothing here</p></body></html>") == {}

    def test_empty_html_returns_empty_dict(self):
        assert _extract_broker("") == {}
