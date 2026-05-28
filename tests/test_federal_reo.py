"""Tests for the federal REO trio (USDA / Treasury / VRM VA REO)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.reo.usda_rd import USDARuralDevelopment
from foreclosure_scraper.scrapers.reo.treasury_seized import TreasurySeizedRealProperty
from foreclosure_scraper.scrapers.reo.vrm_va_reo import VRMPropertiesVAREO


# ---- VRM (now a live HTML scraper, no longer a render-required skeleton) -----

def test_vrm_class_metadata():
    """VRM was wired to parse vrmproperties.com HTML directly (plain GET,
    no headless render). Pin the current contract; fetch() is exercised
    live by the weekly run, not here, to avoid a network dependency."""
    s = VRMPropertiesVAREO()
    assert s.slug == "reo.vrm_va_reo"
    assert s.requires_render is False
    assert s.expected_min_count == 0


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
