"""servicelink_auction._fetch_state: a transient transport/timeout error on the
listings-API call gets retried, not treated as "this state's whole scrape failed."

Found 2026-10-17 (gap-sweep continuation): this file has exactly one network call
site, `_fetch_state()`'s `c.get(API, params=params, follow_redirects=True)` against
the public ui.exostechnology.com JSON API. The surrounding try/except caught
`Exception` but only logged + `break`-ed -- it never re-attempted -- the same
http_client-style bare-call gap already fixed tonight for the Column legal-notice
API scraper, spartan_weekly_legals.py, and the shared arcgis_webmap.query_features().
`http_client.client()` deliberately runs with `retries=0` on its transport and
expects every caller to wrap its own `AsyncRetrying` (see http_client.py's `client()`
comment). The `for page in range(1, _MAX_PAGES + 1)` pagination loop is sequential
and dependent (each page needs the prior page's continuationToken), not a fan-out
over independent items, and NC/SC each normally resolve in 1-2 pages -- so a
transient blip on page 1 zeroed that whole state's result for the run, with no
date-window fallback to self-heal later (this source is in main.DATELESS_OK_SOURCES).

Note: unlike arcgis_webmap.query_features (which lets the exhausted retry's
exception propagate to its caller), _fetch_state's own outer try/except
intentionally swallows a still-failing call after the retry budget is spent and
just stops paginating that state -- that give-up-gracefully behavior is unchanged
and correct here (main.py's per-state try/except in fetch() is the next line of
defense). What changed is that a *transient* blip now gets up to 3 tries before
that give-up path kicks in, instead of giving up on the very first one.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import servicelink_auction as sla

STATE = "NC"


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyClient:
    """Raises on the first N-1 `.get()` calls, then serves a real (empty,
    terminal -- no continuationToken) page so pagination stops cleanly."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, params=None, follow_redirects=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"data": [], "continuationToken": None, "searchResultCount": 0})


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same technique as the arcgis_webmap reference test: swap the module's
    # wait_exponential_jitter for a near-instant one so retry tests don't sleep
    # through real exponential backoff (initial=1, max=8 seconds).
    monkeypatch.setattr(sla, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2)
    rows = asyncio.run(sla._fetch_state(c, STATE))
    assert c.calls == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_does_not_hang_and_gives_up_cleanly():
    """After stop_after_attempt(3) is exhausted, AsyncRetrying (reraise=True)
    re-raises into _fetch_state's own except-Exception-and-break -- so the call
    finishes (no infinite hang) and the state's pagination stops, same as the
    pre-fix give-up behavior, just after 3 tries instead of 1."""
    c = _FlakyClient(fail_times=99)
    rows = asyncio.run(sla._fetch_state(c, STATE))
    assert c.calls == 3
    assert rows == []


def test_a_read_timeout_is_also_retried():
    c = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = asyncio.run(sla._fetch_state(c, STATE))
    assert c.calls == 2
    assert rows == []


def test_a_real_http_error_status_is_not_retried():
    """A non-200 status is a handled case (log + break), not a transport
    failure -- it must fail the attempt immediately, not eat 3 tries."""
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, follow_redirects=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    c = _BadStatusClient()
    rows = asyncio.run(sla._fetch_state(c, STATE))
    assert c.calls == 1
    assert rows == []


def test_a_successful_first_page_is_not_retried_at_all():
    class _OkClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, follow_redirects=None):
            self.calls += 1
            return _FakeResp({"data": [], "continuationToken": None, "searchResultCount": 0})

    c = _OkClient()
    rows = asyncio.run(sla._fetch_state(c, STATE))
    assert c.calls == 1
    assert rows == []
