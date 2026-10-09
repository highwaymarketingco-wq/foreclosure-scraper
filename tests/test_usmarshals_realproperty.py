"""usmarshals_realproperty.py was rewritten 2026-10-01 (national-auction-
tier audit, batch 4). The old target URL (usmarshals.gov/.../real-property/)
is a hard 404; the agency's current Asset Forfeiture page says real
property is now sold via RealLook.com, an independent contractor's site.
The old scraper's extraction method was also exactly the fabricated-row
shape this project has been bitten by before -- a generic street/city/
state/zip regex scanned across the WHOLE page body with no connection to a
real listing boundary, so any address text anywhere on the page (nav,
footer, an unrelated example) could become a fake Listing. Rewritten to
parse RealLook's own structured list cards and <dt>/<dd> detail blocks."""
import re

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.national.usmarshals_realproperty import (
    _CARD_RE,
    _parse_detail,
)

# Trimmed, live-captured list-page fragment (2026-10-01).
_LIST_HTML = """
<div class="row property-grid">
  <div class="col-sm-6 property-grid-item-container">
    <div class="card property-grid-item">
      <a href="/properties/5972-0" class="card-anchor"></a>
      <div class="card-body">
        <h5 class="card-title"><span class="property-price">7,270,000</span></h5>
        <p class="card-text">2118 US Highway 41 S, Calhoun, GA 30701</p>
      </div>
    </div>
  </div>
  <div class="col-sm-6 property-grid-item-container">
    <div class="card property-grid-item">
      <a href="/properties/11182-0" class="card-anchor"></a>
      <div class="card-body">
        <h5 class="card-title"><span class="property-price">159,500</span></h5>
        <p class="card-text">267 Bell Rd, Mayesville, SC 29104</p>
      </div>
    </div>
  </div>
</div>
"""

# Trimmed, live-captured detail page (property_id 11182-0, 2026-10-01).
_DETAIL_ON_MARKET = """
<h1 class="property-price display-4">159,500</h1>
<h2>267 Bell Rd, Mayesville, SC 29104</h2>
<p class="lead"><span class="property-detail"><span class="property-detail-value">6,600</span><span class="property-detail-label">sqft</span></span><span class="property-detail"><span class="property-detail-value">3</span><span class="property-detail-label">acre lot</span></span></p>
<dl>
    <dt>Property Type</dt>
    <dd>Commercial</dd>
    <dt>Status</dt>
    <dd><span class="badge rounded-pill bg-success">On Market</span></dd>
    <dt>Occupied</dt>
    <dd>No</dd>
</dl>
<dl>
    <dt>Year Built</dt>
    <dd>2019</dd>
    <dt>County</dt>
    <dd>Lee</dd>
    <dt>Coordinates</dt>
    <dd><a href="https://www.google.com/maps/place/34.096306, -80.266139">34.096306,  -80.266139</a></dd>
</dl>
<dl>
    <dt>Broker</dt>
    <dd>
        Brandon Paynetest<br />
        +1 (843) 555-0550<br />
        Broker ID: 66802
    </dd>
</dl>
<div class="property-files">
    <ul><li><a href="https://reallook.com/storage/properties/11182-0/files/brochure.pdf">brochure.pdf</a></li></ul>
</div>
<img src="https://reallook.com/storage/properties/11182-0/images/mkt_01.jpg">
<img src="https://reallook.com/storage/properties/11182-0/images/mkt_02.jpg">
"""

_DETAIL_UNDER_CONTRACT = _DETAIL_ON_MARKET.replace(
    '<span class="badge rounded-pill bg-success">On Market</span>',
    '<span class="badge rounded-pill bg-warning">Under Contract</span>',
)

_ADDR = "267 Bell Rd, Mayesville, SC 29104"


def test_card_regex_finds_href_and_address_pairs():
    pairs = _CARD_RE.findall(_LIST_HTML)
    assert ("/properties/5972-0", "2118 US Highway 41 S, Calhoun, GA 30701") in pairs
    assert ("/properties/11182-0", "267 Bell Rd, Mayesville, SC 29104") in pairs


def test_on_market_property_parses_with_all_fields():
    li = _parse_detail(_DETAIL_ON_MARKET, "/properties/11182-0", _ADDR)
    assert li is not None
    assert li.street_address == "267 Bell Rd"
    assert li.city == "Mayesville"
    assert li.state == "SC"
    assert li.zip_code == "29104"
    assert li.county == "Lee County"
    assert li.opening_bid == 159500.0
    assert li.living_sqft == 6600.0
    assert li.acreage == 3.0
    assert li.year_built == 2019
    assert li.property_kind == PropertyKind.COMMERCIAL
    assert li.case_number == "usmarshals-reallook-11182-0"


def test_broker_name_and_phone_are_cleanly_separated():
    """Regression pin: the raw <dd> text has the name, phone, and
    "Broker ID: N" all run together across <br/> breaks -- must not leak
    into a single garbled trustee string."""
    li = _parse_detail(_DETAIL_ON_MARKET, "/properties/11182-0", _ADDR)
    assert li.trustee == "Brandon Paynetest"
    assert li.raw["usmarshals"]["broker_phone"] == "+1 (843) 555-0550"
    assert "Broker ID" not in li.trustee


def test_broker_contact_is_surfaced_into_notice_contact():
    """EXTRACTION-COMPLETENESS 2026-10-03: broker_name/broker_phone were
    already parsed but only stashed under raw["usmarshals"], a key nothing
    downstream reads for contactability. Must also land in
    raw["notice_contact"] -- the key enrich_surface_contacts.py's existing
    phone surfacer reads -- so this real, reachable broker phone actually
    surfaces instead of sitting unused."""
    li = _parse_detail(_DETAIL_ON_MARKET, "/properties/11182-0", _ADDR)
    nc = li.raw["notice_contact"]
    assert nc["name"] == "Brandon Paynetest"
    assert nc["phone"] == "+1 (843) 555-0550"
    assert nc["contact_role"] == "listing broker"


def test_brochure_pdf_is_wired_not_dropped_by_shared_junk_filter():
    """Regression pin: the shared harvest_document_links() junk-denylist
    excludes "brochure" by default (reasonable for other sources), but it
    is the one real per-property document RealLook publishes -- must still
    reach raw["documents"]."""
    li = _parse_detail(_DETAIL_ON_MARKET, "/properties/11182-0", _ADDR)
    assert li.raw["documents"] == [
        "https://reallook.com/storage/properties/11182-0/files/brochure.pdf"
    ]
    assert li.raw["document_url"] == li.raw["documents"][0]


def test_real_photos_are_captured_and_not_mixed_into_documents():
    li = _parse_detail(_DETAIL_ON_MARKET, "/properties/11182-0", _ADDR)
    photos = li.raw["images"]["real"]
    assert "https://reallook.com/storage/properties/11182-0/images/mkt_01.jpg" in photos
    assert not any("/images/" in d for d in li.raw["documents"])


def test_under_contract_status_is_dropped_not_actionable():
    li = _parse_detail(_DETAIL_UNDER_CONTRACT, "/properties/11182-0", _ADDR)
    assert li is None


def test_out_of_core_state_is_dropped():
    ga_addr = "2118 US Highway 41 S, Calhoun, GA 30701"
    li = _parse_detail(_DETAIL_ON_MARKET.replace("SC 29104", "GA 30701"), "/properties/5972-0", ga_addr)
    assert li is None
