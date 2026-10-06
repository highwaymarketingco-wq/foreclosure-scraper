"""national.foreclosure_dot_com -- event loop + block-signal regression (batch 16).

Two bugs, same scraper, found together 2026-10-04 (national.* extraction-
completeness audit) while re-verifying the 2026-10-01 event-loop fix:

1. The event-loop fix itself (asyncio.to_thread around a fully-synchronous
   curl_cffi body) was a correct FIX but not the simplest one available.
   Rewriting `_fetch_search`/`_fetch_city` as native coroutines that
   `await get_text_impersonate(...)` at every page fetch keeps the event
   loop free by construction (no thread hop needed) -- these tests confirm
   that still holds.
2. THE SEVERE ONE: live-reproduced a hard 403 ("VPN or proxy") from
   foreclosure.com on every search/city URL as of 2026-10-04, and the run
   logs show this has been the case since ~2026-08-29 (5,483 real rows on
   2026-08-27, then 0 on every run through 2026-09-25). The OLD code's raw
   `curl_cffi.requests.get()` + `r.status_code != 200: return out` check
   swallowed that block completely -- `safe_run()` saw a clean empty
   result with nothing to promote, so every run logged OUTCOME_ZERO
   ("ran clean but returned 0 rows") instead of OUTCOME_BLOCKED for over a
   month. `get_text_impersonate()` records a block signal
   (`http_client._block_holder`) BEFORE raising, which `safe_run()` reads
   via `take_block_signal()` to correctly reclassify a swallowed-exception
   zero-result run as BLOCKED -- the raw curl_cffi call bypassed that
   mechanism entirely.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from foreclosure_scraper.base_scraper import OUTCOME_BLOCKED, OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national.foreclosure_dot_com import ForeclosureDotCom

# No "<N> Foreclosure Listings" title and no JSON-LD -> _get_total returns 0
# (single page) and no listings parse -- the content does not matter here,
# only that each "network" call takes real wall-clock time so a still-
# blocked event loop would visibly starve the heartbeat below.
_PAGE = "<html><body>" + ("x" * 6000) + "</body></html>"
_CALL_DELAY_S = 0.01


async def _fake_get_text_impersonate(url, **kwargs):
    await asyncio.sleep(_CALL_DELAY_S)  # simulates real network latency
    return _PAGE


@pytest.mark.asyncio
async def test_fetch_does_not_block_the_event_loop():
    heartbeats = {"n": 0}

    async def _heartbeat():
        while True:
            await asyncio.sleep(0.005)
            heartbeats["n"] += 1

    with patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.get_text_impersonate",
        side_effect=_fake_get_text_impersonate,
    ):
        hb_task = asyncio.create_task(_heartbeat())
        scraper = ForeclosureDotCom()
        await scraper.fetch()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    assert heartbeats["n"] > 3, (
        f"only {heartbeats['n']} heartbeats ticked while fetch() ran -- "
        "the event loop was blocked, the fix regressed"
    )


@pytest.mark.asyncio
async def test_fetch_still_returns_normally():
    """Functional-equivalence guard: must cleanly return an empty list
    (no JSON-LD/table in the fake page) rather than raise or hang."""
    with patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.get_text_impersonate",
        side_effect=_fake_get_text_impersonate,
    ):
        scraper = ForeclosureDotCom()
        out = await scraper.fetch()

    assert out == []


@pytest.mark.asyncio
async def test_a_block_on_every_url_degrades_gracefully_without_raising():
    """THE core bug this batch fixed: a block/403 on every URL (the live,
    current, real state of this host -- reproduced live 2026-10-04) must
    not crash fetch() -- it should swallow the exception per-URL (as
    before) and return an empty list, so `safe_run()`'s own
    take_block_signal() check (exercised by get_text_impersonate recording
    the block before raising, not tested here directly) is what promotes
    this to BLOCKED rather than a silent, indistinguishable ZERO_RESULT."""
    async def _always_blocked(url, **kwargs):
        raise RuntimeError("impersonate got 403 for " + url)

    with patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.get_text_impersonate",
        side_effect=_always_blocked,
    ):
        scraper = ForeclosureDotCom()
        out = await scraper.fetch()

    assert out == []


@pytest.mark.asyncio
async def test_a_real_403_is_classified_blocked_not_zero_via_safe_run(monkeypatch):
    """The actual severe bug, end to end through safe_run() (not just
    fetch() in isolation): a 403 from the real curl-cffi transport layer
    must make safe_run() report OUTCOME_BLOCKED, not OUTCOME_ZERO. This
    mocks at the `curl_cffi.requests.AsyncSession` level (the lowest layer
    get_text_impersonate actually calls) so the REAL block-recording code
    in http_client._impersonate_fetch runs for real, instead of mocking
    get_text_impersonate itself and bypassing that mechanism entirely --
    which is exactly how the old raw-curl_cffi code silently defeated it.

    Trimmed to a single SEARCH_URLS/CITY_URLS entry each: get_text_
    impersonate retries a blocked call 3x with REAL exponential-jitter
    backoff (not mocked here, since the backoff itself is part of the
    real transport this test deliberately exercises), and the full
    SEARCH_URLS + CITY_URLS lists (~32 URLs) would make this test take
    several real minutes if every one were retried 3x.
    """
    import foreclosure_scraper.scrapers.national.foreclosure_dot_com as mod

    monkeypatch.setattr(mod, "SEARCH_URLS", (("NC", "https://www.foreclosure.com/listing/search?q=NC"),))
    monkeypatch.setattr(mod, "CITY_URLS", (("NC", "https://www.foreclosure.com/listings/charlotte-nc/"),))

    class _FakeResp:
        def __init__(self):
            self.status_code = 403
            self.text = (
                "Sorry, access to this resource is restricted... "
                "VPN or proxy"
            )

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _FakeResp()

    with patch("curl_cffi.requests.AsyncSession", lambda **kw: _FakeSession()):
        scraper = ForeclosureDotCom()
        scraper.disabled = False   # the source is disabled (wall); this tests the transport path
        out = await scraper.safe_run()

    assert out == []
    assert scraper.last_outcome == OUTCOME_BLOCKED, (
        f"expected OUTCOME_BLOCKED, got {scraper.last_outcome!r} "
        f"({scraper.last_reason!r}) -- a real 403 is being silently "
        "reported as a clean zero-result run again"
    )


@pytest.mark.asyncio
async def test_the_walled_source_is_disabled_and_sends_no_request():
    """2026-10-06: foreclosure.com has answered every request since the 2026-09-23 run with its
    403 network-security page (Mac and VM). A wall is not retried: safe_run() reports DORMANT
    and never reaches the transport."""
    calls = []

    async def _no_network(url, **kwargs):
        calls.append(url)
        raise AssertionError("a disabled source must not send a request")

    scraper = ForeclosureDotCom()
    assert scraper.disabled and "403" in scraper.disabled_reason
    with patch("foreclosure_scraper.scrapers.national.foreclosure_dot_com.get_text_impersonate",
               side_effect=_no_network):
        out = await scraper.safe_run()
    assert out == [] and calls == []
    assert scraper.last_outcome == OUTCOME_DORMANT
