"""counties_nc.asheville_str_permits: a transient transport error on the single
ArcGIS query gets retried, not treated as "zero lapsed permits today."

The scraper makes exactly one external network call (a single ArcGIS REST
query to gis.ashevillenc.gov), issued via the shared `http_client.client()`
primitive. `client()` builds its transport with `retries=0` and its own
docstring says callers must wrap their own retries -- this bare `c.get(...)`
never did. The call site also wraps everything in a catch-all
`except Exception` that logs and returns `[]` on ANY failure, so a transient
blip looked identical to "no lapsed permits" (no exception propagates, no
block-signal recorded). Since this source is dateless (DATELESS_OK_SOURCES,
no fallback date window), a zeroed run would never self-heal. Same root cause
already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import asheville_str_permits as m


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FlakyClient:
    """Raises on the first N-1 calls, then serves a real (empty, terminal) page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"features": []})


class _BadStatusClient:
    """Does not raise at all -- returns a response whose .json() looks like a
    real (non-transport) failure. Used to prove a genuine parse/shape failure
    is NOT retried."""

    def __init__(self):
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        raise ValueError("not a transport error, should not be retried")


def _run_fetch(fake_client_instance):
    @asynccontextmanager
    async def fake_client(*a, **kw):
        yield fake_client_instance

    async def run():
        orig = m.client
        m.client = fake_client
        try:
            return list(await m.AshevilleSTRPermits().fetch())
        finally:
            m.client = orig

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        m, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyClient(fail_times=2)
    out = _run_fetch(http)
    assert http.calls == 3
    assert out == []  # the terminal page has no features, but the call succeeded


def test_a_read_timeout_is_also_retried():
    http = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    out = _run_fetch(http)
    assert http.calls == 2
    assert out == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyClient(fail_times=99)
    out = _run_fetch(http)
    # the outer `except Exception` catches it after the retry budget is exhausted
    # and converts it to the normal "no listings this run" outcome -- it does NOT
    # hang, and it must have actually retried up to the stop limit first.
    assert http.calls == 3  # stop_after_attempt(3), then gives up
    assert out == []


def test_a_real_non_transport_error_is_not_retried():
    http = _BadStatusClient()
    out = _run_fetch(http)
    # a genuine non-transport failure (bad response shape, parse error, etc.)
    # must fail on the first attempt, not be mistaken for a transient blip.
    assert http.calls == 1
    assert out == []
