"""Tests for the federal REO trio (USDA RD / Treasury seized / VRM VA REO).

2026-06-19: the Charlotte demolition tests were removed — charlotte_demolition
was dropped in 2d242c8 (Charlotte/Mecklenburg is a denied county, out of scope),
so the stale import here errored on collection and blocked the whole suite.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.reo.usda_rd import USDARuralDevelopment
from foreclosure_scraper.scrapers.reo.treasury_seized import TreasurySeizedRealProperty
from foreclosure_scraper.scrapers.reo.vrm_va_reo import VRMPropertiesVAREO


# ---- VRM (now a working HTTP scraper, not the old skeleton) ------------------
# 2026-06-19: VRM was implemented since these tests were written — it now returns
# real NC+SC listings, so the old skeleton-empty / render-required assertions were
# stale (and hit the live network). Assert stable metadata only.

def test_vrm_metadata():
    s = VRMPropertiesVAREO()
    assert s.slug == "reo.vrm_va_reo"
    assert s.category == "federal_reo"
    assert s.expected_min_count == 0
    assert "VRM" in s.name


# ---- USDA scraper class metadata ---------------------------------------------

def test_usda_scraper_class_metadata():
    s = USDARuralDevelopment()
    assert s.slug == "reo.usda_rd"
    assert s.expected_min_count == 0


# ---- USDA re-enabled + freeze-hardening --------------------------------------
# 2026-07-01: re-enabled after the 2026-06-27 concurrency freeze. The fix bounds
# every JSP round-trip with asyncio.wait_for(_STEP_TIMEOUT_S) and gates the whole
# state/kind/county matrix on a _TOTAL_BUDGET_S wall-clock deadline, so fetch()
# always returns inside timeout_s even if an individual step wedges.

def test_usda_is_re_enabled():
    s = USDARuralDevelopment()
    # Must be OFF the disabled list so safe_run actually runs it (not DORMANT).
    assert s.disabled is False


def test_usda_budget_bail_stops_matrix_without_network():
    """A spent deadline makes fetch() return [] and touch NO network step."""
    import foreclosure_scraper.scrapers.reo.usda_rd as u

    # Force the wall-clock budget to be already exhausted the moment fetch starts.
    with patch.object(u, "_TOTAL_BUDGET_S", -1.0), \
            patch.object(u, "_fetch_state", new=AsyncMock()) as fake_state:
        s = USDARuralDevelopment()
        out = list(asyncio.run(s.fetch()))

    assert out == []
    # Deadline is spent before the first (state, kind) pair, so _fetch_state
    # (the thing that opens the HTTP client) is never even called.
    fake_state.assert_not_called()


def test_usda_active_counties_step_timeout_is_swallowed():
    """A wedged GET is bounded by _STEP_TIMEOUT_S and yields [] (never hangs)."""
    import foreclosure_scraper.scrapers.reo.usda_rd as u

    async def _never_returns(*a, **k):
        await asyncio.sleep(3600)  # simulate a wedged JSP round-trip

    fake_client = AsyncMock()
    fake_client.get = _never_returns

    async def _run():
        # Shrink the per-step cap so the test is fast; the real cap is 30s.
        with patch.object(u, "_STEP_TIMEOUT_S", 0.05):
            return await u._active_counties(fake_client, "SC", "SFH")

    codes = asyncio.run(_run())
    assert codes == []


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
