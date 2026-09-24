"""Three lower-severity findings from the 2026-09-24 event-loop-starvation
sweep (see tests/test_zombie_properties_event_loop.py and
tests/test_irs_treasury_event_loop.py for the two "High" severity fixes in
that same sweep, and their MEASURED live evidence). These three were flagged
"Low"/"Medium" -- bounded call counts, not confirmed live incidents -- but
share the identical anti-pattern: a blocking (synchronous) network call
inside an `async def`, which freezes the WHOLE event loop for every other
concurrent scraper for as long as that one call takes, not just this
scraper's own declared timeout_s.

national.williams_auctions: 2 sequential curl_cffi cf.get() calls, no loop.
national.sc_public_index (_curl_search_county): a curl_cffi Session reused
  across a loop of search-prefix POSTs; already yields between iterations
  via `await asyncio.sleep(REQUEST_DELAY)`, so never a total freeze, but each
  individual blocking call (up to 30s) still froze the loop while in flight.
counties_sc.cherokee_delinquent_tax: a single synchronous
  urllib.request.urlopen() call, replaced outright with the async
  http_client.get_text() (this file's own get_bytes() calls already use the
  same async client) rather than thread-wrapped, since a clean async
  replacement was available.

Each test below proves the fix genuinely frees the event loop by racing a
heartbeat coroutine against the scraper's real code path with the network
call mocked to take measurable wall-clock time.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import Mock, patch

import pytest


async def _race_heartbeat(coro):
    heartbeats = {"n": 0}

    async def _heartbeat():
        while True:
            await asyncio.sleep(0.005)
            heartbeats["n"] += 1

    hb_task = asyncio.create_task(_heartbeat())
    await coro
    hb_task.cancel()
    try:
        await hb_task
    except asyncio.CancelledError:
        pass
    return heartbeats["n"]


# --- williams_auctions ------------------------------------------------------

def _fake_cf_response(text: str, status_code: int = 200) -> Mock:
    r = Mock()
    r.status_code = status_code
    r.text = text
    return r


@pytest.mark.asyncio
async def test_williams_auctions_fetch_does_not_block_event_loop():
    from foreclosure_scraper.scrapers.national.williams_auctions import WilliamsAuctions

    def _slow_get(url, **kw):
        time.sleep(0.05)
        return _fake_cf_response("<html>" + "x" * 5000 + "</html>")

    with patch("foreclosure_scraper.scrapers.national.williams_auctions.cf.get",
               side_effect=_slow_get):
        n = await _race_heartbeat(WilliamsAuctions().fetch())

    assert n > 3, f"only {n} heartbeats ticked -- event loop was blocked"


# --- cherokee_delinquent_tax --------------------------------------------------

@pytest.mark.asyncio
async def test_cherokee_media_fetch_uses_the_async_client_not_urllib():
    """The old urllib.request import must be gone entirely -- a stray
    synchronous fallback path would silently reintroduce the freeze."""
    import foreclosure_scraper.scrapers.counties_sc.cherokee_delinquent_tax as mod
    assert not hasattr(mod, "urllib"), (
        "urllib is still imported -- the sync urlopen() path may have crept back in"
    )


@pytest.mark.asyncio
async def test_cherokee_fetch_does_not_block_on_a_slow_media_response():
    from foreclosure_scraper.scrapers.counties_sc.cherokee_delinquent_tax import (
        CherokeeDelinquentTaxScraper,
    )

    async def _slow_get_text(url, **kw):
        await asyncio.sleep(0.05)
        return "[]"  # empty media list -> clean early return, no PDF fetch needed

    async def _drain_fetch():
        # fetch() is an async generator (it `yield`s Listings further down for
        # the PDF-row case); consuming it fully is the async equivalent of
        # awaiting a coroutine for this race.
        scraper = CherokeeDelinquentTaxScraper()
        async for _ in scraper.fetch():
            pass

    with patch(
        "foreclosure_scraper.scrapers.counties_sc.cherokee_delinquent_tax.get_text",
        side_effect=_slow_get_text,
    ):
        n = await _race_heartbeat(_drain_fetch())

    assert n > 3, f"only {n} heartbeats ticked -- event loop was blocked"


# --- sc_public_index (_curl_search_county) -----------------------------------

@pytest.mark.asyncio
async def test_sc_public_index_charleston_search_does_not_block_event_loop():
    from foreclosure_scraper.scrapers.national import sc_public_index as mod

    disclaimer_html = (
        '<input type="hidden" name="__VIEWSTATE" value="v1"/>'
        '<input type="hidden" name="__EVENTVALIDATION" value="e1"/>'
    )

    class _FakeSession:
        def get(self, url, **kw):
            time.sleep(0.02)
            return _fake_cf_response(disclaimer_html)

        def post(self, url, **kw):
            time.sleep(0.02)
            return _fake_cf_response(disclaimer_html)

    with patch("curl_cffi.requests.Session", return_value=_FakeSession()), \
         patch.object(mod, "SEARCH_PREFIXES", ["A", "B", "C"]), \
         patch.object(mod, "REQUEST_DELAY", 0):
        n = await _race_heartbeat(mod._curl_search_county("Charleston"))

    assert n > 3, f"only {n} heartbeats ticked -- event loop was blocked"
