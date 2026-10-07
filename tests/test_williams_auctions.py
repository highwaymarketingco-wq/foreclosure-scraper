"""Parser tests for the rewritten national.williams (Williams & Williams
Foreclosure/Trustee auctions via bid.auctionnetwork.com).

Fixtures are trimmed from pages fetched live on 2026-10-02, including the two
layout quirks that produced wrong data on the first pass:
  * a completed sale's "Sale Location" line is a STATUS SENTENCE ("Sale
    completed, Upset Bid Period open"), not a courthouse name, and has no
    `detail__time` block at all (the live-auction-timing div is empty).
  * the page's own chrome (favicon .ico via a `<link>` tag, the site logo
    `<img>`, and two Content/Images/*.png button icons) sits right next to
    the one real per-listing document and would outrank it if run through
    the shared document_links.harvest_document_links() scan -- so this
    scraper uses its own narrow `class="detail__pdf"` selector instead (same
    posture as national.usmarshals_realproperty's brochure-PDF regex).
"""
from datetime import datetime

import pytest

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.national import williams_auctions as _wa


class _FrozenDatetime(datetime):
    """The courthouse line says 'Oct 5 at 1:00 PM' with no year: the parser picks the next such date, so
    the expected 2026 date silently became 2027 once the real clock passed Oct 5 2026. Pin the clock."""

    @classmethod
    def utcnow(cls):
        return cls(2026, 9, 28, 12, 0, 0)


@pytest.fixture(autouse=True)
def _pin_the_clock(monkeypatch):
    monkeypatch.setattr(_wa, "datetime", _FrozenDatetime)
from foreclosure_scraper.scrapers.national.williams_auctions import (
    _DETAIL_HREF_RE,
    _PDF_LINK_RE,
    _parse_detail,
    _parse_sale_dt,
)

# Trimmed /Home/AuctionPartialView?listingTypes=Classified&searchState=NC fragment.
_LIST_HTML = """
<div class="row" data-listingid="5650786">
    <div class="col-xs-12 col-sm-4 img-container listImg">
<a href="/Listing/Details/5650786/3489-LAMP-LIGHT-DR-RANDLEMAN-NC-27317-403323">
    <img src="https://auctionnetworkimages.blob.core.windows.net/assets/media/x_fullsize.jpg" alt="Listing Image" />
</a>
    </div>
</div>
<div class="row" data-listingid="8463529">
    <div class="col-xs-12 col-sm-4 img-container listImg">
<a href="/Listing/Details/8463529/614-SEBASTIAN-LN-PLEASANT-GARDEN-NC-27313-404179">
    <img src="https://auctionnetworkimages.blob.core.windows.net/assets/media/y_fullsize.jpg" alt="Listing Image" />
</a>
    </div>
</div>
"""

# Williams & Williams detail page for a PENDING courthouse sale, with a filed
# case number (23-12118-FC03) -- real property, real case, live 2026-10-02.
_DETAIL_PENDING = """
<title>Auction Network - 3489 LAMP LIGHT DR, RANDLEMAN, NC 27317 - #403323</title>
<link rel="shortcut icon" href="https://auctionnetworkimages.blob.core.windows.net/assets/media/favicon-hash.ico" />
<img src="https://auctionnetworkimages.blob.core.windows.net/assets/media/logo-hash_largesize.jpg" class="site_logo_responsive" />
<span class="propertyType">Residential</span>
<div class="bedBathDiv">Randolph County</div>
<div class="feature-content">
    <div class="feature-head">Year Built</div>
    <div class="feature-val">---</div>
</div>
<div class="feature-content">
    <div class="feature-head">Sub Type</div>
    <div class="feature-val">Residential</div>
</div>
<img id="previewimg" class="img-responsive full" src="https://auctionnetworkimages.blob.core.windows.net/assets/media/08721150_largesize.jpg" alt="Listing Image" />
<img class="img-thumbnail" src="https://auctionnetworkimages.blob.core.windows.net/assets/media/08721150_thumbfit.jpg" data-full-size-src="https://auctionnetworkimages.blob.core.windows.net/assets/media/08721150_largesize.jpg" alt="Listing Image" />
<img class="img-thumbnail" src="https://auctionnetworkimages.blob.core.windows.net/assets/media/99676ab1_thumbfit.jpg" data-full-size-src="https://auctionnetworkimages.blob.core.windows.net/assets/media/99676ab1_largesize.jpg" alt="Listing Image" />
<p><strong>Auction Information:</strong> <span>800-801-8003</span></p>
<p><strong>Foreclosure/Trustee </strong> <span><strong>#23-12118-FC03 </strong></span></p>
<div class="detail__show-time-classified">
    <strong>LIVE Auction</strong>
    <span class="detail__time">Oct 5 at 1:00 PM</span>
</div>
<p><strong>Sale Location: </strong>Randolph County Courthouse</p>
<img class="pdficon" src="Content/images/Icons/pdf_icon_24x24.png" height="24" width="24" alt="PDF" />
<img src="Content/Images/exclamation.png" class="awe-refresh-alert" />
<img src="Content/Images/printer.png" />
<a href="Listing/GetForeclosurePDF" class="detail__pdf">
    <img class="pdficon" src="Content/images/Icons/pdf_icon_24x24.png" height="24" width="24" alt="PDF" />Foreclosure Auction Info.Pdf
</a>
"""

# Same site, a listing whose sale has ALREADY happened -- NC's statutory
# 10-day post-sale upset-bid window. No case number filed, no detail__time
# block at all, and "Sale Location" is a status sentence, not a courthouse.
_DETAIL_UPSET_BID = """
<title>Auction Network - 614  SEBASTIAN LN, PLEASANT GARDEN, NC 27313 - #404179</title>
<span class="propertyType">Residential</span>
<div class="bedBathDiv">Guilford County</div>
<div class="feature-content">
    <div class="feature-head">Year Built</div>
    <div class="feature-val">---</div>
</div>
<div class="feature-content">
    <div class="feature-head">Sub Type</div>
    <div class="feature-val">Residential</div>
</div>
<img class="img-thumbnail" src="thumb1.jpg" data-full-size-src="https://auctionnetworkimages.blob.core.windows.net/assets/media/1490f7ea_largesize.jpg" alt="Listing Image" />
<p><strong>Auction Information:</strong> <span>800-801-8003</span></p>
<p><strong>Foreclosure/Trustee </strong> <span><strong># </strong></span></p>
<div class="live-auction-timing">
</div>
<p><strong>Sale Location: </strong>Sale completed, Upset Bid Period open</p>
<a href="Listing/GetForeclosurePDF" class="detail__pdf">Foreclosure Auction Info.Pdf</a>
"""

_PENDING_URL = "https://bid.auctionnetwork.com/Listing/Details/5650786/3489-LAMP-LIGHT-DR-RANDLEMAN-NC-27317-403323"
_UPSET_URL = "https://bid.auctionnetwork.com/Listing/Details/8463529/614-SEBASTIAN-LN-PLEASANT-GARDEN-NC-27313-404179"


def test_list_fragment_yields_both_detail_hrefs():
    hrefs = _DETAIL_HREF_RE.findall(_LIST_HTML)
    assert hrefs == [
        "/Listing/Details/5650786/3489-LAMP-LIGHT-DR-RANDLEMAN-NC-27317-403323",
        "/Listing/Details/8463529/614-SEBASTIAN-LN-PLEASANT-GARDEN-NC-27313-404179",
    ]


def test_pending_sale_parses_address_county_and_case_number():
    li = _parse_detail(_DETAIL_PENDING, _PENDING_URL)
    assert li is not None
    assert li.street_address == "3489 LAMP LIGHT DR"
    assert li.city == "RANDLEMAN"
    assert li.state == "NC"
    assert li.zip_code == "27317"
    assert li.county == "Randolph County"
    assert li.case_number == "23-12118-FC03"
    assert li.listing_type is ListingType.FORECLOSURE_SALE
    assert li.property_kind is PropertyKind.SINGLE_FAMILY
    assert li.foreclosure_process == "power_of_sale"


def test_pending_sale_date_and_location_come_from_the_courthouse_line():
    li = _parse_detail(_DETAIL_PENDING, _PENDING_URL)
    assert li.sale_location == "Randolph County Courthouse"
    assert li.auction_status is None
    assert li.sale_date == datetime(2026, 10, 5, 13, 0)
    assert li.sale_time == "Oct 5 at 1:00 PM"


def test_pending_sale_gallery_is_both_largesize_images_in_order():
    li = _parse_detail(_DETAIL_PENDING, _PENDING_URL)
    assert li.raw["images"]["real"] == [
        "https://auctionnetworkimages.blob.core.windows.net/assets/media/08721150_largesize.jpg",
        "https://auctionnetworkimages.blob.core.windows.net/assets/media/99676ab1_largesize.jpg",
    ]


def test_auction_info_phone_is_surfaced_into_notice_contact():
    """EXTRACTION-COMPLETENESS 2026-10-03: auction_info_phone was already
    parsed but only stashed under raw["williams"], a key nothing downstream
    reads for contactability. Must also land in raw["notice_contact"] (the
    key enrich_surface_contacts.py's existing phone surfacer reads) so this
    real, dialable auction-desk number actually surfaces."""
    li = _parse_detail(_DETAIL_PENDING, _PENDING_URL)
    assert li.raw["notice_contact"]["phone"] == "800-801-8003"
    assert li.raw["notice_contact"]["contact_role"] == "Williams & Williams auction desk"


def test_pending_sale_document_is_the_pdf_link_only_not_the_sites_own_chrome():
    """The bug: the favicon .ico, the site logo .jpg, and the pdficon/
    exclamation/printer .png button images all satisfy document_links.py's
    generic extension scan and would outrank (or replace) the one real
    document. This scraper's own `class="detail__pdf"` selector must pick up
    ONLY the real link."""
    li = _parse_detail(_DETAIL_PENDING, _PENDING_URL)
    assert li.raw["documents"] == ["https://bid.auctionnetwork.com/Listing/GetForeclosurePDF"]
    assert li.raw["document_url"] == "https://bid.auctionnetwork.com/Listing/GetForeclosurePDF"
    assert "favicon" not in li.raw["document_url"]
    assert "logo" not in li.raw["document_url"]


def test_pdf_link_regex_ignores_non_detail_pdf_anchors():
    html = ('<a href="/some/other/link.pdf" class="other">x</a>'
            '<a href="Listing/GetForeclosurePDF" class="detail__pdf">y</a>')
    assert _PDF_LINK_RE.findall(html) == ["Listing/GetForeclosurePDF"]


def test_upset_bid_sale_has_no_courthouse_and_no_case_number():
    """auction_status is normalized to the exact string models.py /
    national.nc_upset_bids already use for this state ("upset_bid_period"),
    not the raw page sentence -- the sentence is kept verbatim in
    raw.williams.sale_status_text for provenance instead."""
    li = _parse_detail(_DETAIL_UPSET_BID, _UPSET_URL)
    assert li is not None
    assert li.sale_location is None
    assert li.auction_status == "upset_bid_period"
    assert li.raw["williams"]["sale_status_text"] == "Sale completed, Upset Bid Period open"
    assert li.sale_date is None


def test_upset_bid_case_number_falls_back_to_the_property_id():
    """No case number has been filed/published for this one -- the fallback
    keeps every row addressable (a case_number of None would make multiple
    rows collide in anything that keys off it) without fabricating a court
    docket number that does not exist."""
    li = _parse_detail(_DETAIL_UPSET_BID, _UPSET_URL)
    assert li.case_number == "auctionnetwork-404179"


def test_double_space_in_the_page_title_does_not_leak_into_street_address():
    """'614  SEBASTIAN LN' (double space, exactly as the live title renders
    it) must normalize to a single space, not become part of a street number
    parsing trap the way the sibling auction_bank_reo scraper hit before."""
    li = _parse_detail(_DETAIL_UPSET_BID, _UPSET_URL)
    assert li.street_address == "614 SEBASTIAN LN"


def test_non_nc_sc_detail_page_is_dropped():
    html = _DETAIL_PENDING.replace("RANDLEMAN, NC 27317", "ATLANTA, GA 30301")
    assert _parse_detail(html, _PENDING_URL) is None


# -- _parse_sale_dt: the page never publishes a year --------------------------

def test_sale_dt_uses_the_current_year_when_the_date_is_still_ahead():
    now = datetime(2026, 10, 2)
    assert _parse_sale_dt("Oct 20 at 10:00 AM", now) == datetime(2026, 10, 20, 10, 0)


def test_sale_dt_rolls_to_next_year_when_the_month_has_already_passed():
    now = datetime(2026, 10, 2)
    assert _parse_sale_dt("Jan 5 at 9:00 AM", now) == datetime(2027, 1, 5, 9, 0)


def test_sale_dt_handles_pm_and_noon_and_midnight_hour_conversion():
    now = datetime(2026, 10, 2)
    assert _parse_sale_dt("Oct 20 at 12:00 PM", now) == datetime(2026, 10, 20, 12, 0)
    assert _parse_sale_dt("Oct 20 at 12:00 AM", now) == datetime(2026, 10, 20, 0, 0)


def test_sale_dt_defaults_to_noon_when_no_time_is_given():
    now = datetime(2026, 10, 2)
    assert _parse_sale_dt("Oct 20", now) == datetime(2026, 10, 20, 12, 0)


def test_sale_dt_returns_none_for_blank_or_unparseable_text():
    now = datetime(2026, 10, 2)
    assert _parse_sale_dt(None, now) is None
    assert _parse_sale_dt("", now) is None
    assert _parse_sale_dt("TBD", now) is None
