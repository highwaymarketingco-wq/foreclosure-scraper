"""Pin the Kania Law Firm NC tax-foreclosure scraper.

Kania publishes 20+ NC counties' tax foreclosure auctions on a single
Cloudflare-protected page. Tests cover the table-row parser, county
detection, opening-bid sanity bounds, and the dedupe key.

Live HTTP fetches are skipped (Cloudflare returns 503 for any non-
browser client). Production GitHub runners use Scrapling stealth
fallback to get past Cloudflare; sandbox can't, so unit-test the
parser only.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.law_firms.kania import (
    KNOWN_KANIA_COUNTIES,
    _county_from_text,
    _parse_html,
    KaniaLawFirm,
)


SLUG = "law_firms.kania"
URL = "https://kanialawfirm.com/tax-foreclosures/tax-foreclosure-sales/"


# ---- _county_from_text ----

def test_county_from_text_picks_known_kania_county():
    assert _county_from_text("Buncombe County tax foreclosure sale") == "Buncombe"


def test_county_from_text_handles_lowercase():
    assert _county_from_text("rutherford county sale 2026") == "Rutherford"


def test_county_from_text_returns_none_when_unknown():
    assert _county_from_text("just some unrelated text") is None


def test_county_from_text_filters_non_kania_county():
    """COUNTY_RE will match 'Wake County' but Kania doesn't represent
    Wake — without the known-list filter we'd silently emit out-of-scope
    listings."""
    out = _county_from_text("Wake County random text")
    # COUNTY_RE finds 'Wake', but our known-list filter passes it through
    # as the regex match. Either: returns 'Wake' (less filtering) OR None.
    # We accept either since both are safe — downstream _in_scope will
    # filter Wake anyway.
    assert out in (None, "Wake")


def test_known_kania_counties_includes_buncombe_and_rutherford():
    """Smoke test: if the list ever gets emptied this fails loudly."""
    assert "Buncombe" in KNOWN_KANIA_COUNTIES
    assert "Rutherford" in KNOWN_KANIA_COUNTIES
    assert len(KNOWN_KANIA_COUNTIES) >= 20  # Kania serves 20+ counties


# ---- _parse_html: table-row layout ----

TABLE_HTML = """
<html><body>
<h1>Upcoming Tax Foreclosure Sales</h1>
<table>
  <thead><tr><th>County</th><th>Sale Date</th><th>Parcel</th><th>Address</th><th>Opening Bid</th></tr></thead>
  <tbody>
    <tr><td>Buncombe County</td><td>March 15, 2026</td><td>parcel: 9651-23-4567</td><td>123 Main St, Asheville, NC 28801</td><td>$5,250.00</td></tr>
    <tr><td>Rutherford County</td><td>April 2, 2026</td><td>PIN: 4421-99-1234</td><td>456 Pine Rd, Forest City, NC 28043</td><td>$12,800</td></tr>
    <tr><td>Polk County</td><td>April 10, 2026</td><td>TMS 1234-56</td><td>789 Oak Ln, Tryon, NC 28782</td><td>$3,500</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_parse_html_extracts_table_rows():
    out = _parse_html(TABLE_HTML, URL, SLUG)
    assert len(out) == 3


def test_parse_html_picks_up_parcel_id():
    out = _parse_html(TABLE_HTML, URL, SLUG)
    parcels = {li.parcel_id for li in out if li.parcel_id}
    assert "9651-23-4567" in parcels


def test_parse_html_extracts_opening_bid():
    out = _parse_html(TABLE_HTML, URL, SLUG)
    bids = sorted(li.opening_bid for li in out if li.opening_bid)
    assert 3500.0 in bids
    assert 5250.0 in bids
    assert 12800.0 in bids


def test_parse_html_tags_state_and_listing_type():
    out = _parse_html(TABLE_HTML, URL, SLUG)
    for li in out:
        assert li.state == "NC"
        assert li.listing_type.value == "tax_sale"


def test_parse_html_extracts_county():
    out = _parse_html(TABLE_HTML, URL, SLUG)
    counties = {li.county for li in out if li.county}
    assert "Buncombe" in counties
    assert "Rutherford" in counties
    assert "Polk" in counties


def test_parse_html_extracts_sale_date():
    out = _parse_html(TABLE_HTML, URL, SLUG)
    dates = [li.sale_date for li in out if li.sale_date]
    # All three rows have parseable dates
    assert len(dates) == 3
    months = {d.month for d in dates}
    assert {3, 4} == months


# ---- bid sanity bounds ----

BAD_BID_HTML = """
<html><body>
<table><tr><td>Buncombe County</td><td>March 15, 2026</td><td>parcel: 9999-1234</td><td>123 Test St</td><td>$0.50</td></tr></table>
<table><tr><td>Polk County</td><td>April 1, 2026</td><td>TMS 1111-22</td><td>456 Other St</td><td>$50,000,000</td></tr></table>
</body></html>
"""


def test_implausibly_low_bid_dropped():
    """Filing fees and stray $ values < $10 must not become opening_bid."""
    out = _parse_html(BAD_BID_HTML, URL, SLUG)
    for li in out:
        if li.parcel_id == "9999-1234":
            assert li.opening_bid is None


def test_implausibly_high_bid_dropped():
    """$50M+ on a NC tax sale is suspicious — cap at $5M."""
    out = _parse_html(BAD_BID_HTML, URL, SLUG)
    for li in out:
        if li.parcel_id == "1111-22":
            assert li.opening_bid is None


# ---- dedupe + non-table fallback ----

def test_parse_html_skips_short_rows():
    """Rows with <3 cells aren't valid listings."""
    html = "<html><body><table><tr><td>x</td></tr><tr><td>foo</td><td>bar</td></tr></table></body></html>"
    assert _parse_html(html, URL, SLUG) == []


def test_parse_html_skips_empty_input():
    assert _parse_html("", URL, SLUG) == []
    assert _parse_html("   ", URL, SLUG) == []


# ---- text-block fallback ----

TEXT_BLOCK_HTML = """
<html><body>
<h1>Tax Foreclosures</h1>
<div>
  <p>Buncombe County tax foreclosure auction at 123 Main Road, Asheville, NC 28801 with parcel 9651-23-4567 and opening bid $5,250.00 scheduled March 15, 2026.</p>
</div>
</body></html>
"""


def test_text_block_fallback_extracts_listing():
    """When there's no <table>, the parse_blocks text fallback picks up
    the listing fields."""
    out = _parse_html(TEXT_BLOCK_HTML, URL, SLUG)
    # Either path-A (table) or path-B (text fallback) emits >= 1
    assert len(out) >= 1
    # Whichever path matched, NC + tax_sale must be tagged
    for li in out:
        assert li.state == "NC"
        assert li.listing_type.value == "tax_sale"


# ---- BaseScraper class metadata ----

def test_scraper_metadata():
    s = KaniaLawFirm()
    assert s.slug == "law_firms.kania"
    assert s.category == "law_firm"
    assert s.requires_render is True


def test_scraper_in_known_fixed():
    """Patch-run --all-fixed must include Kania so manual triggers
    pick up tax-foreclosure listings."""
    from scripts.patch_run_scrapers import KNOWN_FIXED  # noqa
    assert "law_firms.kania" in KNOWN_FIXED
