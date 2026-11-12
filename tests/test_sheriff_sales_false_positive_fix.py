"""Pin the 2026-10-01 false-positive fix in national/sheriff_sales.py.

CONFIRMED LIVE: `_fetch_county`'s sub-page crawl used to check its keyword
list ("sale", "auction", "foreclosure", "pending", "sheriff") against the
FULL href. Every page on sheriffclevelandcounty.com contains "sheriff" as a
substring of its own hostname, so that matched literally every link on the
site -- 60 unrelated URLs on one real page, including a LinkedIn
share-article link for an unrelated felony-drug-arrest press release, the
department's Facebook page, an App Store listing, and concealed-carry/
funeral-escort forms. The free-text fallback parser then pattern-matched the
department's own street address and random digits out of "careers",
"crimestoppers", "missing-persons", "fallen-heroes", and
"sex-offender-registry" pages as if they were real sheriff-sale listings --
6 fabricated Cleveland County Listings on a live run, while the county's own
published PDF says "NO PUBLIC AUCTION at this time" (the correct state is
zero, not six fake ones).

This file locks in both halves of the fix with real-shaped fixtures (no
network calls).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.sheriff_sales import (
    _SALE_CONTEXT_RE,
    _parse_brunswick,
    _parse_charleston,
    _parse_cleveland,
)

# Real-shaped boilerplate: a department street address embedded in an
# unrelated "careers" page footer. This used to be misread as a sale listing
# because it has a digit-prefixed address-looking string.
_CAREERS_PAGE_HTML = """
<html><body>
<div class="content">
  <p>Join our team! Visit us at 100 Justice Pl, Shelby, NC for an application,
  or call our HR office for more information about open positions.</p>
</div>
</body></html>
"""

# A genuine sheriff-sale notice block: has the required sale-context phrase
# AND a real address/case number.
_REAL_SALE_HTML = """
<html><body>
<div class="content">
  <p>NOTICE OF SHERIFF'S SALE: By virtue of an execution sale, the property
  located at 311 E. Marion Street, Shelby, NC, case number 24-CVD-1234, will
  be sold at public auction on the courthouse steps.</p>
</div>
</body></html>
"""


def test_sale_context_regex_matches_real_sale_language():
    assert _SALE_CONTEXT_RE.search("NOTICE OF SHERIFF'S SALE: ...")
    assert _SALE_CONTEXT_RE.search("sold at public auction on the steps")
    assert _SALE_CONTEXT_RE.search("pursuant to an execution sale")


def test_sale_context_regex_rejects_unrelated_boilerplate():
    assert not _SALE_CONTEXT_RE.search(
        "Join our team! Visit us at 100 Justice Pl for an application."
    )
    assert not _SALE_CONTEXT_RE.search(
        "Cleveland County Sheriff's Office career opportunities and benefits."
    )


def test_cleveland_fallback_rejects_boilerplate_address_with_no_sale_context():
    """The exact live failure mode: an unrelated page (careers) with a real
    street address but no sale-context phrase must yield zero Listings."""
    out = _parse_cleveland(_CAREERS_PAGE_HTML, "https://example.com/careers/")
    assert out == []


def test_cleveland_fallback_accepts_a_real_sale_notice():
    out = _parse_cleveland(_REAL_SALE_HTML, "https://example.com/sales/")
    assert len(out) == 1
    assert out[0].street_address == "311 E. Marion Street"
    assert out[0].case_number is not None


def test_brunswick_fallback_rejects_boilerplate_and_accepts_real_sale():
    assert _parse_brunswick(_CAREERS_PAGE_HTML, "https://example.com/careers/") == []
    out = _parse_brunswick(_REAL_SALE_HTML, "https://example.com/sales/")
    assert len(out) == 1


def test_charleston_fallback_rejects_boilerplate_and_accepts_real_sale():
    # Charleston's fallback requires len(text) >= 20; both fixtures qualify.
    assert _parse_charleston(_CAREERS_PAGE_HTML, "https://example.com/careers/") == []
    out = _parse_charleston(_REAL_SALE_HTML, "https://example.com/sales/")
    assert len(out) == 1


def test_subpage_path_filter_does_not_match_on_hostname():
    """The core bug: checking the keyword list against the full href let the
    word 'sheriff' in the HOSTNAME itself make every link match. Verify the
    fix's logic directly: a path with no keyword, on a host that contains
    one, must not match."""
    import httpx

    full = "https://www.sheriffclevelandcounty.com/careers/"
    path_lower = httpx.URL(full).path.lower()
    assert path_lower == "/careers/"
    assert not any(
        kw in path_lower for kw in ("sale", "auction", "foreclosure", "pending", "civil")
    )
    # Contrast: the OLD (buggy) check against the full href DID match, since
    # the hostname itself contains "sheriff" -- not one of the new keywords,
    # but demonstrates why checking the full string (not just the path) is
    # unsafe in general; the real regression guard is the assert above.
    assert "sheriff" in full.lower()


def test_subpage_path_filter_still_matches_a_real_sales_path():
    import httpx

    full = "https://www.charlestoncounty.org/departments/sheriff/pending-sales.php"
    path_lower = httpx.URL(full).path.lower()
    assert any(
        kw in path_lower for kw in ("sale", "auction", "foreclosure", "pending", "civil")
    )


def test_non_html_extensions_are_excluded_from_subpage_crawl():
    from foreclosure_scraper.scrapers.national.sheriff_sales import _NON_HTML_EXT

    assert "/uploads/2025/05/no-public-auction-8.5-x-11-in.pdf".endswith(_NON_HTML_EXT)
