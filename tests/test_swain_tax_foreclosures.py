"""Swain County NC tax foreclosures — WP Download Manager notice PDF.

HERMES sec 8 audit, 2026-10-01. The old scraper looked for PDF links on the
county HOMEPAGE, which never had any (always 0 rows). Fixed to follow the
real chain: tax-office page -> "Notice of Foreclosure Sales" detail page ->
the WP Download Manager data-downloadurl link (not a plain href).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc.swain_tax_foreclosures import (
    SwainTaxForeclosures,
    _find_notice_page,
    _parse_text_rows,
)

TAX_OFFICE_HTML = (
    '<div class="elementor-toggle-item">'
    '<a class="elementor-toggle-title">Notice of Foreclosure Sales</a>'
    '<div><p><a href="https://www.swaincountync.gov/download/'
    'tax-notice-of-foreclosure/">click here for information</a></p></div>'
    '</div>'
)

# Trimmed, field-faithful reproduction of the live WPDM detail page
# (swaincountync.gov/download/tax-notice-of-foreclosure/, read 2026-10-01):
# a self-referential canonical/breadcrumb link (also matches the "notice"
# doc-hint) PLUS the real download button, whose href is a dead "#" with the
# live file URL only in data-downloadurl.
NOTICE_PAGE_HTML = (
    '<link rel="canonical" href="https://www.swaincountync.gov/download/'
    'tax-notice-of-foreclosure/" />'
    '<a href="https://www.swaincountync.gov/download/tax-notice-of-foreclosure/">'
    'TAX - NOTICE OF FORECLOSURE</a>'
    '<a class="download-on-click btn btn-primary" rel="nofollow" href="#" '
    'data-downloadurl="https://www.swaincountync.gov/download/'
    'tax-notice-of-foreclosure/?wpdmdl=9278&refresh=6abf1d00dc68a1790909696">'
    'Download</a>'
)


def test_find_notice_page_follows_the_toggle_link():
    url = asyncio.run(_find_notice_page(TAX_OFFICE_HTML))
    assert url == "https://www.swaincountync.gov/download/tax-notice-of-foreclosure/"


def test_notice_page_self_referential_link_does_not_win_over_real_download():
    """Regression: the canonical/breadcrumb link to the notice page ITSELF
    also contains 'notice' (matches document_links' doc-hint) and used to
    rank ahead of (or tie with) the real data-downloadurl file link, so the
    scraper tried to download the HTML page as if it were a PDF."""
    from foreclosure_scraper.document_links import harvest_document_links
    page_url = "https://www.swaincountync.gov/download/tax-notice-of-foreclosure/"
    doc_urls = harvest_document_links(NOTICE_PAGE_HTML, base_url=page_url)
    wpdm = [u for u in doc_urls if "wpdmdl=" in u]
    assert wpdm, "the real WPDM download link must be found at all"
    chosen = wpdm[0] if wpdm else [u for u in doc_urls if u.rstrip("/") != page_url.rstrip("/")][0]
    assert "wpdmdl=9278" in chosen


def test_parse_text_rows_still_works_for_a_future_non_scanned_notice():
    text = "123 Main St Parcel 123456789 $4,521.00\nnotice heading line\n"
    out = _parse_text_rows(text, "http://x.pdf")
    assert len(out) == 1
    assert out[0].parcel_id == "123456789"
    assert out[0].judgment_amount == 4521.0


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.swain_tax_foreclosures" in {s.slug for s in all_scrapers()}
    assert SwainTaxForeclosures.slug == "counties_nc.swain_tax_foreclosures"
