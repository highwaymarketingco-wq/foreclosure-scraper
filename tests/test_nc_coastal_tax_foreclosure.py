"""Coastal-NC county tax-foreclosure scraper (Brunswick / Onslow / Carteret).

Built 2026-06-25 for the NEW COASTAL NC FORECLOSURE SOURCES track. Fixtures are
captured from the live county pages (structures verified 2026-06-25):
  Brunswick — /912/Legal-Notices HTML "Parcel # <X> <date>" + per-parcel PDF link
  Onslow    — /DocumentCenter PDF text "Parcel <X> <addr> $<bid>" under a
              "Foreclosure Sales <DATE> at <TIME>" header
  Carteret  — /1149 fixed-header HTML table
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc.nc_coastal_tax_foreclosure import (
    SLUG,
    NCCoastalTaxForeclosure,
    parse_brunswick,
    parse_carteret,
    parse_onslow_pdf_text,
)

# --- Brunswick fixture: the live list markup shape (CivicPlus, zero-width sp) ---
_BRUNSWICK_HTML = """
<html><body>
<h1>Legal Notices</h1>
<p>Click the link for each parcel number to view and/or download the notice of sale.</p>
<div>
  <a href="/DocumentCenter/View/7205">&#8203;Parcel # 156LA00502&#8203;</a> April 10, 2026
  <a href="/DocumentCenter/View/7290">&#8203;Parcel # 22900053&#8203;</a> May 8, 2026
  <a href="/DocumentCenter/View/7537">&#8203;Parcel # 156NE015&#8203;</a> June 26, 2026
</div>
</body></html>
"""

# --- Onslow fixture: exact PDF text layout (one header, two rows) ---
_ONSLOW_PDF_TEXT = """UPCOMING FORECLOSURE SALES
*Click on the blue hyperlink for more information on the parcel
Foreclosure Sales June 30, 2026 at 12:00pm at the Courthouse Door
Parcel Property Address Opening Bid
Parcel 036764 1363 Kinston Hwy, Richlands $44,423.34
Parcel 112233 55 Marine Blvd, Jacksonville $12,000.00
"""

# --- Carteret fixture: populated table (between-cycle it's empty) ---
_CARTERET_HTML = """
<html><body>
<table>
<tr><th>Name</th><th>Parcel ID</th><th>Minimum Opening Bid</th><th>Owner</th>
<th>Legal Description</th><th>Address</th><th>Date of Sale</th>
<th>Deed Link</th><th>Deed Book</th><th>Deed Page</th></tr>
<tr><td>Carteret Co. v. Doe</td><td>730612345678000</td><td>$8,500.00</td>
<td>DOE JOHN</td><td>LOT 4 BLK A EMERALD ISLE</td><td>101 Ocean Dr, Emerald Isle</td>
<td>July 15, 2026</td><td><a href="/x">Deed</a></td><td>1450</td><td>222</td></tr>
<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
</table>
</body></html>
"""

_CARTERET_EMPTY_HTML = """
<html><body>
<table>
<tr><th>Name</th><th>Parcel ID</th><th>Minimum Opening Bid</th><th>Owner</th>
<th>Legal Description</th><th>Address</th><th>Date of Sale</th>
<th>Deed Link</th><th>Deed Book</th><th>Deed Page</th></tr>
<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# Brunswick
# ---------------------------------------------------------------------------
def test_brunswick_parses_parcel_and_date():
    out = parse_brunswick(_BRUNSWICK_HTML)
    assert len(out) == 3
    by_parcel = {li.parcel_id: li for li in out}
    assert set(by_parcel) == {"156LA00502", "22900053", "156NE015"}
    li = by_parcel["156NE015"]
    assert li.county == "Brunswick"
    assert li.state == "NC"
    assert li.source == SLUG
    assert li.listing_type == ListingType.TAX_SALE
    assert li.foreclosure_process == "tax"
    assert li.sale_date is not None and li.sale_date.year == 2026 and li.sale_date.month == 6
    # PDF notice link carried for downstream reference.
    assert "/DocumentCenter/View/7537" in (li.source_url or "")


def test_brunswick_empty_when_no_notices():
    assert parse_brunswick("<html><body>No notices.</body></html>") == []


# ---------------------------------------------------------------------------
# Onslow
# ---------------------------------------------------------------------------
def test_onslow_parses_rows_with_header_date():
    out = parse_onslow_pdf_text(_ONSLOW_PDF_TEXT)
    assert len(out) == 2
    a = next(li for li in out if li.parcel_id == "036764")
    assert a.county == "Onslow"
    assert a.street_address == "1363 Kinston Hwy"
    assert a.city == "Richlands"
    assert a.opening_bid == 44423.34
    assert a.sale_date is not None and a.sale_date.month == 6 and a.sale_date.day == 30
    assert a.sale_time and a.sale_time.lower().startswith("12:00")
    assert a.foreclosure_process == "tax"
    assert a.source == SLUG


def test_onslow_skips_column_header_row():
    # The "Parcel Property Address Opening Bid" title row must not become a row.
    out = parse_onslow_pdf_text(_ONSLOW_PDF_TEXT)
    assert all(li.parcel_id not in (None, "Property") for li in out)
    assert all("Opening" not in (li.street_address or "") for li in out)


def test_onslow_empty_when_no_rows():
    txt = "UPCOMING FORECLOSURE SALES\nNo sales scheduled at this time.\n"
    assert parse_onslow_pdf_text(txt) == []


# ---------------------------------------------------------------------------
# Carteret
# ---------------------------------------------------------------------------
def test_carteret_parses_table_row():
    out = parse_carteret(_CARTERET_HTML)
    assert len(out) == 1
    li = out[0]
    assert li.county == "Carteret"
    assert li.parcel_id == "730612345678000"
    assert li.street_address == "101 Ocean Dr, Emerald Isle"
    assert li.owner_name == "DOE JOHN"
    assert li.opening_bid == 8500.0
    assert li.sale_date is not None and li.sale_date.month == 7 and li.sale_date.day == 15
    assert li.foreclosure_process == "tax"
    assert li.source == SLUG


def test_carteret_empty_table_yields_nothing():
    # Between sale cycles the table has only blank rows — must yield 0, not crash.
    assert parse_carteret(_CARTERET_EMPTY_HTML) == []


# ---------------------------------------------------------------------------
# Registration + live smoke (network-gated)
# ---------------------------------------------------------------------------
def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    slugs = {s.slug for s in all_scrapers()}
    assert SLUG in slugs


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live county sites + NC OneMap — slow; set RUN_NETWORK_TESTS=1",
)
def test_live_yields_coastal_rows_with_coords():
    out = list(asyncio.run(NCCoastalTaxForeclosure().fetch()))
    # Brunswick + Onslow almost always have at least one active notice.
    assert out, "expected at least one coastal NC tax-foreclosure row"
    for li in out:
        assert li.state == "NC"
        assert li.county in ("Brunswick", "Onslow", "Carteret")
        assert li.parcel_id  # every emitted row carries a parcel
    # The geo step should resolve coordinates for most rows so the oceanfront
    # gate can place them at ingest.
    geocoded = [li for li in out if li.latitude is not None]
    assert geocoded, "expected NC OneMap to resolve coordinates for some rows"
