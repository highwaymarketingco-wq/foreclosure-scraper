"""Tests for the federal REO trio + Charlotte demolition feed."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.reo.usda_rd import USDARuralDevelopment
from foreclosure_scraper.scrapers.reo.treasury_seized import TreasurySeizedRealProperty
from foreclosure_scraper.scrapers.reo.vrm_va_reo import VRMPropertiesVAREO
from foreclosure_scraper.scrapers.city_websites.charlotte_demolition import (
    CharlotteDemolitionOrders,
)


# ---- VRM (skeleton) ---------------------------------------------------------

def test_vrm_classified_render_required():
    s = VRMPropertiesVAREO()
    assert s.slug == "reo.vrm_va_reo"
    assert getattr(s, "requires_render", False) is True


def test_vrm_skeleton_returns_empty():
    s = VRMPropertiesVAREO()
    out = list(asyncio.run(s.fetch()))
    assert out == []


# ---- USDA scraper class metadata ---------------------------------------------

def test_usda_scraper_class_metadata():
    s = USDARuralDevelopment()
    assert s.slug == "reo.usda_rd"
    assert s.expected_min_count == 0


# ---- Treasury parser end-to-end ---------------------------------------------

TREASURY_FIXTURE = """
<html><body>
<h1>Real Property Auctions</h1>
<p>The following properties are scheduled for sale:</p>
<table><tr><td>
  Property Address: 123 Main Street, Asheville, NC 28801
  Sale Date: 06/15/2026 — Minimum bid $45,000
</td></tr>
<tr><td>
  Property Address: 456 Oak Avenue, Charleston, SC 29401
  Sale Date: 07/01/2026 — Minimum bid $89,500
</td></tr>
<tr><td>
  Property Address: 789 Pine Lane, Newark, NJ 07102
  Sale Date: 06/20/2026 — Minimum bid $125,000
</td></tr></table>
""" + "<p>Lorem ipsum padding.</p>" * 100 + "</body></html>"


def test_treasury_parses_carolina_listings_only():
    fake_response = type("R", (), {"status_code": 200, "text": TREASURY_FIXTURE})()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)

    class FakeCM:
        async def __aenter__(self): return fake_client
        async def __aexit__(self, *a): return None

    with patch(
        "foreclosure_scraper.scrapers.reo.treasury_seized.client",
        return_value=FakeCM(),
    ):
        s = TreasurySeizedRealProperty()
        out = list(asyncio.run(s.fetch()))

    states = sorted(li.state for li in out)
    assert states == ["NC", "SC"]    # NJ filtered out
    bids = sorted(li.opening_bid for li in out if li.opening_bid)
    assert bids == [45000.0, 89500.0]


# ---- Charlotte demolition end-to-end ----------------------------------------

CHARLOTTE_FIXTURE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "CaseType": "Housing",
                "CaseNumber": "20240050927",
                "CaseStatus": "Demolition Ordered",
                "Address": "1234 Hawthorne Ln",
                "City": "Charlotte",
                "ZipCode": "28204",
                "OrderDate": 1725148800000,
            },
            "geometry": {"type": "Point", "coordinates": [-80.83, 35.22]},
        },
        {
            "type": "Feature",
            "properties": {
                "CaseType": "Building",
                "CaseNumber": "20240050928",
                "CaseStatus": "Compliance Pending",
                "Address": "567 Beatties Ford Rd",
                "ZipCode": "28216",
                "OrderDate": 1725148800000,
            },
            "geometry": {"type": "Point", "coordinates": [-80.86, 35.27]},
        },
        {  # Duplicate case# — should dedupe
            "type": "Feature",
            "properties": {
                "CaseNumber": "20240050927",
                "Address": "1234 Hawthorne Ln",
            },
            "geometry": {"type": "Point", "coordinates": [-80.83, 35.22]},
        },
    ],
}


def test_charlotte_demolition_parses_geojson():
    fake_response = type("R", (), {
        "status_code": 200,
        "text": json.dumps(CHARLOTTE_FIXTURE),
        "json": lambda self=None: CHARLOTTE_FIXTURE,
    })()
    fake_response.json = lambda: CHARLOTTE_FIXTURE
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)

    class FakeCM:
        async def __aenter__(self): return fake_client
        async def __aexit__(self, *a): return None

    with patch(
        "foreclosure_scraper.scrapers.city_websites.charlotte_demolition.client",
        return_value=FakeCM(),
    ):
        s = CharlotteDemolitionOrders()
        out = list(asyncio.run(s.fetch()))

    # 2 unique cases (3rd was a duplicate case#)
    assert len(out) == 2
    cases = sorted(li.case_number for li in out)
    assert cases == ["20240050927", "20240050928"]
    # Coordinates set
    li = next(x for x in out if x.case_number == "20240050927")
    assert li.latitude == 35.22 and li.longitude == -80.83
    assert li.state == "NC"
    assert li.county == "Mecklenburg"
    assert li.street_address == "1234 Hawthorne Ln"
    assert li.zip_code == "28204"
    # Description includes case_type + status
    assert "Housing" in (li.description or "")
    assert "Demolition Ordered" in (li.description or "")
