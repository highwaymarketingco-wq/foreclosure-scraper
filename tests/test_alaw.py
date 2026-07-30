"""Albertelli Law (ALAW) — NC foreclosure sales scraper.

ALAW's NC sales page (alaw.net/foreclosure-sales/north-carolina/) embeds a public,
anonymously-shared SharePoint/Excel-Online workbook. The grid is painted inside
the Office Web Apps (WAC) frame, which inlines its visible cell range as
{"Col":c,"Row":r,"Text":"..."} objects. The scraper captures that bootstrap and
reconstructs the grid; the parser is pure so it is tested against a saved slice of
a REAL capture (tests/fixtures/alaw_nc_wac.txt — header row + three data rows
including the two in-footprint counties, Cleveland and Gaston).

Live network run is opt-in via RUN_NETWORK_TESTS=1 (launches a headless browser).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.law_firms.alaw import (
    Alaw,
    _discover_embed_url,
    parse_wac_cells,
)

FIX = Path(__file__).parent / "fixtures" / "alaw_nc_wac.txt"


def _rows():
    return parse_wac_cells(FIX.read_text(), "https://www.alaw.net/foreclosure-sales/north-carolina/")


def test_parses_data_rows_not_header():
    rows = _rows()
    # Fixture holds 3 data rows (Catawba, Cleveland, Gaston); header excluded.
    assert len(rows) == 3
    assert all(r.listing_type is ListingType.FORECLOSURE_SALE for r in rows)
    assert all(r.source == "law_firms.alaw" for r in rows)
    # The header row must NOT leak in as a listing.
    assert not any((r.street_address or "") == "Address" for r in rows)


def test_field_mapping_and_county_split():
    rows = _rows()
    by_county = {r.county: r for r in rows}
    assert set(by_county) == {"Catawba", "Cleveland", "Gaston"}

    # In-footprint row: Shelby / Cleveland.
    cle = by_county["Cleveland"]
    assert cle.street_address == "1606 S Post Rd"
    assert cle.city == "Shelby"
    assert cle.state == "NC"          # split out of the "NC - Cleveland" cell
    assert cle.zip_code == "28152"
    assert cle.case_number == "24-SP-98"
    assert cle.trustee == "Albertelli Law"
    assert cle.foreclosure_process == "power_of_sale"

    # In-footprint row: Mount Holly / Gaston.
    gas = by_county["Gaston"]
    assert gas.street_address == "109 Clover Street"
    assert gas.city == "Mount Holly"
    assert gas.zip_code == "28120"


def test_sale_date_and_bid_parsed():
    rows = _rows()
    cat = next(r for r in rows if r.county == "Catawba")
    # "8/8/2025" -> Aug 8, 2025
    assert cat.sale_date is not None
    assert (cat.sale_date.year, cat.sale_date.month, cat.sale_date.day) == (2025, 8, 8)
    # Catawba row carries a bid amount (176505.00); the two footprint rows do not.
    assert cat.opening_bid == pytest.approx(176505.00)
    assert next(r for r in rows if r.county == "Cleveland").opening_bid is None


def test_empty_or_garbage_capture_returns_empty():
    assert parse_wac_cells("", "u") == []
    assert parse_wac_cells("no cell objects here at all", "u") == []


def test_discover_embed_url():
    page = (
        '<div><iframe loading="lazy" src="about:blank" '
        'data-lazy-src="https://albertellilaw.sharepoint.com/:x:/s/FCSales/'
        'TOKEN?e=ABC&amp;action=embedview&amp;wdHideGridlines=True"></iframe></div>'
    )
    url = _discover_embed_url(page)
    assert url is not None
    assert url.startswith("https://albertellilaw.sharepoint.com/:x:/s/FCSales/")
    assert "action=embedview" in url
    assert "&amp;" not in url  # HTML entities unescaped
    assert _discover_embed_url("<p>no iframe here</p>") is None


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="live network + headless browser; set RUN_NETWORK_TESTS=1",
)
def test_live_smoke():
    rows = asyncio.run(_collect(Alaw()))
    # Page may sit between refreshes; just assert it runs and rows are well-formed.
    for r in rows:
        assert r.source == "law_firms.alaw"
        assert r.state == "NC"
        assert r.street_address


async def _collect(scraper):
    return list(await scraper.fetch())
