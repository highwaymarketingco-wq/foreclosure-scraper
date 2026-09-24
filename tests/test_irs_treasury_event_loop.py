"""irs_treasury_auctions.fetch() must not block the asyncio event loop.

Same bug class just found and fixed in counties_sc.zombie_properties
(confirmed live: that scraper froze every sibling scraper for 41m50s because
its fetch() had zero `await` points, so asyncio.wait_for could never preempt
it). This scraper had the identical shape: `async def _fetch_irs()` looped
`cf.get(...)` (curl_cffi, fully synchronous/blocking) once for the items page
and once per /ad/ link, with NO await anywhere and NO rate-limit sleep
between iterations at all -- a sleeper risk flagged during the systemic sweep
that found zombie_properties: as of 2026-08-20 there were only ~18 active
auctions, but the loop is unbounded and the site's own latency is untested at
scale, so this could become the next multi-minute freeze with no warning.

Fix: the fully-synchronous body moved to a plain `def _fetch_irs_sync()`,
called via `asyncio.to_thread` from `IRSTreasuryAuctions.fetch()`, so the
event loop stays free regardless of how many ads show up or how slow
irsauctions.gov gets.
"""
from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest

from foreclosure_scraper.scrapers.national.irs_treasury_auctions import (
    IRSTreasuryAuctions,
    _fetch_irs_sync,
)


def _fake_response(text: str, status_code: int = 200) -> Mock:
    r = Mock()
    r.status_code = status_code
    r.text = text
    return r


_ITEMS_HTML = "<html><body>" + "".join(
    f'<a href="/ad/prop{i}">Property {i}</a>' for i in range(30)
) + "</body></html>" + "x" * 1000  # pad past the >=1000-char body-size gate

_AD_HTML_NC = """
<html><body><h1>123 Main St Auction</h1>
<p>123 Main St, Charlotte, NC 28202. Minimum bid: $45,000.</p>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_does_not_block_the_event_loop():
    """Race a heartbeat coroutine against fetch() -- a slow, blocking cf.get()
    loop (simulated here as a real time.sleep inside the mocked call) must not
    starve it."""
    import time

    def _slow_get(url, **kw):
        time.sleep(0.02)  # simulate real network latency per request
        if url.endswith("/auction/items"):
            return _fake_response(_ITEMS_HTML)
        return _fake_response(_AD_HTML_NC)

    heartbeats = {"n": 0}

    async def _heartbeat():
        while True:
            await asyncio.sleep(0.005)
            heartbeats["n"] += 1

    with patch("foreclosure_scraper.scrapers.national.irs_treasury_auctions.cf.get",
               side_effect=_slow_get):
        hb_task = asyncio.create_task(_heartbeat())
        scraper = IRSTreasuryAuctions()
        await scraper.fetch()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    # 30 ad pages x 0.02s + 1 items page x 0.02s = ~0.62s of real blocking work.
    # On the old (blocking) code the heartbeat coroutine never gets scheduled
    # until fetch() returns; with asyncio.to_thread it should tick many times.
    assert heartbeats["n"] > 5, (
        f"only {heartbeats['n']} heartbeats ticked while fetch() ran -- "
        "the event loop was blocked, the fix regressed"
    )


def test_fetch_irs_sync_still_parses_nc_listings_correctly():
    """Functional-equivalence guard: the rename/threading change must not
    change what gets parsed."""
    def _get(url, **kw):
        if url.endswith("/auction/items"):
            return _fake_response(_ITEMS_HTML)
        return _fake_response(_AD_HTML_NC)

    with patch("foreclosure_scraper.scrapers.national.irs_treasury_auctions.cf.get",
               side_effect=_get):
        out = _fetch_irs_sync()

    assert len(out) == 30
    li = out[0]
    assert li.state == "NC"
    assert li.county == "Mecklenburg"
    assert li.opening_bid == 45000
    assert li.source == "national.irs_treasury"


def test_fetch_irs_sync_handles_items_fetch_failure():
    with patch("foreclosure_scraper.scrapers.national.irs_treasury_auctions.cf.get",
               side_effect=Exception("boom")):
        out = _fetch_irs_sync()
    assert out == []
