"""Tests for the shared NC tax-foreclosure helper.

The per-county tax scrapers that used to wrap fetch_county_tax_listings
(Wake/Forsyth/Guilford/New Hanover/Durham) were removed when their
counties fell out of scope. The helper itself is retained (it's the
generic NC county tax parser, also covered by test_nc_tax_parser_fallback)
so these tests pin the standalone parsing functions against fixture HTML.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.counties_nc._nc_tax_helper import (
    _parse_money,
    _parse_sale_date,
    fetch_county_tax_listings,
)


# ---- _parse_money -----------------------------------------------------------

def test_parse_money_with_commas():
    assert _parse_money("$1,234.56") == 1234.56


def test_parse_money_no_commas():
    assert _parse_money("$1234") == 1234.0


def test_parse_money_garbage():
    assert _parse_money("TBD") is None


def test_parse_money_empty():
    assert _parse_money("") is None


# ---- _parse_sale_date -------------------------------------------------------

def test_parse_sale_date_full_format():
    html = "Tax sale on May 27, 2026 at 10:00am at Old Courthouse, 200 N Grove St, Hendersonville, NC 28792."
    sd, loc = _parse_sale_date(html)
    assert sd is not None and sd.year == 2026 and sd.month == 5
    assert loc and "Hendersonville" in loc


def test_parse_sale_date_no_match():
    sd, loc = _parse_sale_date("No sales currently scheduled.")
    assert sd is None
    assert loc is None


# ---- fetch_county_tax_listings end-to-end -----------------------------------

FIXTURE_HTML = """
<html><head><title>Wake Tax Foreclosure</title></head><body>
<h1>Tax Foreclosure Sales</h1>
<p>The next sale is scheduled for June 15, 2026 at 10:00am.
   Location: 316 Fayetteville St, Raleigh, NC 27601 — courthouse steps.</p>
<table>
  <tr><th>Owner</th><th>Parcel #</th><th>Description</th><th>File #</th><th>Bid</th></tr>
  <tr><td>Smith, John</td><td>0123456789</td><td>123 Main St</td><td>26-CV-0042</td><td>$15,432.10</td></tr>
  <tr><td>Doe, Jane</td><td>9876543210</td><td>456 Oak Ave</td><td>26-CV-0043</td><td>$22,000.00</td></tr>
  <tr><td>ACME LLC</td><td>5555555555</td><td>Lot 7 Pine Subd</td><td>26-CV-0044</td><td>TBD</td></tr>
</table>
<p>Buyers must register prior to sale.</p>
</body></html>
"""


def test_fetches_and_parses_table():
    fake_response = type("R", (), {"status_code": 200, "text": FIXTURE_HTML})()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)

    class FakeCM:
        async def __aenter__(self): return fake_client
        async def __aexit__(self, *a): return None

    with patch(
        "foreclosure_scraper.scrapers.counties_nc._nc_tax_helper.client",
        return_value=FakeCM(),
    ):
        listings = asyncio.run(fetch_county_tax_listings(
            slug="counties_nc.wake_tax", county="Wake",
            url="http://example.com",
        ))

    assert len(listings) == 3
    parcels = sorted(li.parcel_id for li in listings)
    assert parcels == ["0123456789", "5555555555", "9876543210"]
    bids = {li.parcel_id: li.opening_bid for li in listings}
    assert bids["0123456789"] == 15432.10
    assert bids["5555555555"] is None  # "TBD" — None
    assert all(li.county == "Wake" and li.state == "NC" for li in listings)
    assert all(li.sale_date and li.sale_date.year == 2026 for li in listings)


def test_returns_empty_on_404():
    fake_response = type("R", (), {"status_code": 404, "text": ""})()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)

    class FakeCM:
        async def __aenter__(self): return fake_client
        async def __aexit__(self, *a): return None

    with patch(
        "foreclosure_scraper.scrapers.counties_nc._nc_tax_helper.client",
        return_value=FakeCM(),
    ):
        listings = asyncio.run(fetch_county_tax_listings(
            slug="x", county="x", url="http://example.com",
        ))
    assert listings == []


def test_returns_empty_on_short_html():
    """A page that returns <500 chars is almost certainly an error page,
    not a real tax-foreclosure list. Parser must reject."""
    fake_response = type("R", (), {"status_code": 200, "text": "<html><body>No sales.</body></html>"})()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)

    class FakeCM:
        async def __aenter__(self): return fake_client
        async def __aexit__(self, *a): return None

    with patch(
        "foreclosure_scraper.scrapers.counties_nc._nc_tax_helper.client",
        return_value=FakeCM(),
    ):
        listings = asyncio.run(fetch_county_tax_listings(
            slug="x", county="x", url="http://example.com",
        ))
    assert listings == []
