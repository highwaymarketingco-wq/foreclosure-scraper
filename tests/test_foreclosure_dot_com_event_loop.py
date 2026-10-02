"""national.foreclosure_dot_com.fetch() must not block the asyncio event loop.

CONFIRMED LIVE 2026-10-01 (per-source audit, Pattern-B sweep): fetch() looped over
SEARCH_URLS and CITY_URLS calling the fully synchronous `_fetch_search`/`_fetch_city`
helpers -- which call `curl_cffi.requests.get()` (a blocking, requests-style call, not
an async session) and sleep between pages with `time.sleep()`, not `asyncio.sleep()` --
with ZERO `await` points anywhere in the coroutine. A coroutine with no await points
cannot be preempted by `asyncio.wait_for` (Task cancellation only takes effect at an
await), so the whole event loop froze for this scraper's entire run: with up to 2
search URLs and 35 city URLs each potentially paginating, a slow/throttled host could
have frozen every sibling scraper in a real `run_local.sh` run for minutes, the same
mechanism `docs/full_run_execution_audit_2026-09-23.md` independently observed around
this scraper's run window (`national.fannie_homepath` timing out nearby) without the
root cause having been found at the time, and the same bug class already fixed in
`zombie_properties.py` and `wnc_rod_foreclosure_starts.py`.

Fix: the synchronous body now runs via `asyncio.to_thread`, so the event loop stays
free for sibling scrapers while this one is busy. This test proves the loop is
genuinely free during fetch() by racing a concurrent asyncio.sleep()-based heartbeat
against it -- on the old (blocking) code the heartbeat would never increment until
fetch() returned; on the fix it increments throughout, mirroring
tests/test_zombie_properties_event_loop.py's pattern for the identical bug class.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from foreclosure_scraper.scrapers.national.foreclosure_dot_com import ForeclosureDotCom


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


# No "<N> Foreclosure Listings" title and no JSON-LD -> _get_total returns 0 (single
# page) and no listings parse -- the content of the response does not matter for this
# test, only that each "network" call and each inter-page sleep takes real wall-clock
# time, so a still-blocked event loop would visibly starve the heartbeat below.
_PAGE = "<html><body>" + ("x" * 6000) + "</body></html>"
_CALL_DELAY_S = 0.01
#: `time.sleep` itself gets patched below (the module-under-test's `time` is the same
#: singleton module object this test file imports) -- capture the REAL function first
#: so the fakes below can still sleep for real without recursing into the mock.
_real_sleep = time.sleep


def _fake_get(url, *args, **kwargs):
    _real_sleep(_CALL_DELAY_S)  # simulates real (blocking) network latency
    return _FakeResponse(_PAGE)


@pytest.mark.asyncio
async def test_fetch_does_not_block_the_event_loop():
    heartbeats = {"n": 0}

    async def _heartbeat():
        while True:
            await asyncio.sleep(0.005)
            heartbeats["n"] += 1

    with patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.cf.get",
        side_effect=_fake_get,
    ), patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.time.sleep",
        side_effect=lambda _s: _real_sleep(_CALL_DELAY_S),
    ):
        hb_task = asyncio.create_task(_heartbeat())
        scraper = ForeclosureDotCom()
        await scraper.fetch()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    # On the old (blocking) code, fetch() never yields, so the heartbeat task --
    # scheduled on the SAME event loop -- gets zero chances to run until fetch() has
    # already returned. asyncio.to_thread keeps the loop free the whole time fetch()
    # is doing real (synchronous) work in a worker thread, so the heartbeat should
    # have ticked many times over the ~37-call run.
    assert heartbeats["n"] > 3, (
        f"only {heartbeats['n']} heartbeats ticked while fetch() ran -- "
        "the event loop was blocked, the fix regressed"
    )


@pytest.mark.asyncio
async def test_fetch_still_returns_normally_after_the_threading_change():
    """Functional-equivalence guard: moving the body into a worker thread via
    asyncio.to_thread must not change behavior, only scheduling."""
    with patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.cf.get",
        side_effect=_fake_get,
    ), patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.time.sleep",
        return_value=None,
    ):
        scraper = ForeclosureDotCom()
        out = await scraper.fetch()

    # No JSON-LD/table in the fake page, so this must cleanly return an empty list
    # rather than raise or hang.
    assert out == []
