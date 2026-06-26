"""Regression tests for the post-sale / nav-chrome junk filters in the two
SC county-tax scrapers (added 2026-06-25).

Background:
  * counties_sc.sc_tax_delinquent was returning 1334 rows — ALL from Pickens
    post-sale RESULT / historical PDFs (header markers "BIDDER #" /
    "SALE/BID PRICE", or "<date> TAX SALE / OWNER (NOW OR FORMERLY)"). These
    are already-auctioned, address-less parcel rows, not fresh pre-sale leads.
  * counties_sc.sc_flc was returning 18 rows — ALL nav-chrome / prose junk
    (county-office addresses, GIS-menu items, copyright footers, JS) with no
    real SC TMS.

These tests lock in the detectors so the junk can't silently come back. Live
end-to-end checks are gated behind RUN_NETWORK_TESTS=1.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_sc.sc_tax_delinquent import (
    SCTaxDelinquent,
    _is_post_sale_filename,
    _is_post_sale_text,
)
from foreclosure_scraper.scrapers.counties_sc.sc_flc import (
    SCForfeitedLand,
    _is_nav_or_contact,
)


# --------------------------------------------------------------------------- #
# sc_tax_delinquent — post-sale RESULT PDF detection                          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name",
    [
        "TAX SALE RESULTS FOR WEBSITE.pdf",
        "2025 Delinquent Tax Sale Results",
        "2024 Tax Sale Results for Web.pdf",
        "2022 DELINQUENT TAX SALE RESULTS FOR WEBSITE.pdf",
        "TAX SALE RESULTS - WEBSITE pdf.pdf",
    ],
)
def test_post_sale_filename_detected(name):
    assert _is_post_sale_filename(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "2026DelinquentTaxList.pdf",          # a genuine pre-sale list
        "document_center/Departments/Delinquent Tax/2019DelSaleListing.pdf",
        "delinquent-tax-2026.pdf",
        "",
    ],
)
def test_non_result_filename_not_flagged(name):
    assert _is_post_sale_filename(name) is False


def test_post_sale_text_modern_results_header():
    # Pickens 2020+ "RESULTS" sheet header
    txt = ("BIDDER # ITEM # MAP/PARCEL # 11-4-2025 TAX SALE "
           "SALE/BID PRICE 2024 TAXES 2025 TAXES")
    assert _is_post_sale_text(txt) is True


def test_post_sale_text_historical_now_or_formerly():
    # Pickens 2014-2019 archived pre-sale listing for a PAST sale —
    # "OWNER (NOW OR FORMERLY)" marks it as already auctioned/historical.
    txt = "11-12-19 TAX SALE\nTAX MAP NUMBER OWNER (NOW OR FORMERLY)"
    assert _is_post_sale_text(txt) is True


def test_genuine_pre_sale_text_not_flagged():
    # A real current delinquent/pre-sale list must still pass through.
    txt = ("2026 Delinquent Tax List\nTMS  Defaulting Taxpayer  "
           "Property Description  Amount Due")
    assert _is_post_sale_text(txt) is False


def test_empty_text_not_flagged():
    assert _is_post_sale_text("") is False
    assert _is_post_sale_text(None) is False  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# sc_flc — nav-chrome / contact-block detection                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "line",
    [
        "© · 2021 Pickens County · 222 McDaniel Avenue, Pickens, SC 29671 ·",
        "GIS & E911 Addressing",
        "GIS & E-911 Addressing",
        "RZ.pagelinkfilter = 'linklevel=0 and linksectionid=0';",
        "Please Contact Planning 864-596-3570 for questions concerning subdividing",
        "Office hours: Monday - Friday 8:30am to 5:00pm",
    ],
)
def test_nav_contact_lines_detected(line):
    assert _is_nav_or_contact(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "5019-19-50-6848 2 COBB STREET, LLC",       # a real TMS parcel row
        "4191-12-86-0828 AIKEN, JILLIAN L.",
        "123 Main Street",                          # plain addr (no nav marker)
    ],
)
def test_real_parcel_or_plain_addr_not_nav(line):
    assert _is_nav_or_contact(line) is False


def test_flc_inline_requires_real_tms_drops_office_address():
    """The exact county-office / footer rows the old harvest emitted must now
    produce nothing: they carry a street suffix but no SC TMS."""
    from foreclosure_scraper.scrapers.counties_sc.sc_flc import PARCEL_RE

    junk_lines = [
        "110 Railroad Ave.",
        "222 McDaniel Avenue, B-2",
        "401 East River Street, Anderson, SC 29624",
        "366 N Church Street",
        "© · 2021 Pickens County · 222 McDaniel Avenue, Pickens, SC 29671 ·",
        "GIS & E911 Addressing",
    ]
    for line in junk_lines:
        # New gate: a line is only emitted if it (a) is not nav/contact AND
        # (b) carries a real TMS. None of the junk lines have a TMS.
        emitted = (not _is_nav_or_contact(line)) and bool(PARCEL_RE.search(line))
        assert emitted is False, f"junk line wrongly emitted: {line!r}"


def test_flc_inline_keeps_real_tms_row():
    from foreclosure_scraper.scrapers.counties_sc.sc_flc import PARCEL_RE
    line = "1234-56-78-901.000  SMITH JOHN  100 Forfeit Ln"
    assert _is_nav_or_contact(line) is False
    assert PARCEL_RE.search(line) is not None


# --------------------------------------------------------------------------- #
# registration sanity                                                          #
# --------------------------------------------------------------------------- #

def test_both_scrapers_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_sc.sc_tax_delinquent" in slugs
    assert "counties_sc.sc_flc" in slugs


# --------------------------------------------------------------------------- #
# live end-to-end (opt-in)                                                     #
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live SC county sites — slow; set RUN_NETWORK_TESTS=1",
)
def test_live_sc_tax_delinquent_excludes_post_sale_pdfs():
    out = list(asyncio.run(SCTaxDelinquent().fetch()))
    # No emitted row may originate from a *result* PDF.
    bad = [li for li in out if "result" in (li.source_url or "").lower()]
    assert bad == [], f"{len(bad)} post-sale RESULT rows leaked through"
    # And every emitted row (if any) must look like a real lead, not the
    # address-less post-sale parcel dump that motivated this filter.
    for li in out:
        assert li.parcel_id or li.street_address


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live SC county sites — slow; set RUN_NETWORK_TESTS=1",
)
def test_live_sc_flc_returns_no_junk():
    out = list(asyncio.run(SCForfeitedLand().fetch()))
    # Every inline-harvested row must carry a real TMS; nav-chrome (no TMS)
    # must be fully gone. PDF-link rows are exempt (they have no parcel yet).
    for li in out:
        if li.raw and li.raw.get("page_url") and not str(li.source_url).lower().endswith(".pdf"):
            # inline body row — must have a TMS
            assert li.parcel_id, f"junk inline row with no TMS: {li.street_address!r}"
        assert not _is_nav_or_contact(li.description or "")
