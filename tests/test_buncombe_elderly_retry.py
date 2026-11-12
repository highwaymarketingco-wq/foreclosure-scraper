"""buncombe_elderly.BuncombeElderly.fetch: a transient transport error on the ArcGIS
page fetch gets retried, not treated as "the whole scrape failed."

Found 2026-10-17 (gap-sweep): fetch() calls `c.get(QUERY_URL, params=params)` directly
on the raw httpx.AsyncClient yielded by http_client.client() (retries=0 by design --
callers must wrap their own AsyncRetrying), guarded only by `try: ... except Exception:
break`. The very first call is at offset=0, before anything is appended to `out`, so a
single transient blip (connection reset, timeout) zeroed the whole scrape's result. Because
buncombe_elderly is registered in main.DATELESS_OK_SOURCES (no fallback date window), a
zeroed run cannot self-heal and silently reported as healthy. Same bug shape already fixed
tonight in a Column legal-notice API scraper, spartan_weekly_legals.py, and the shared
arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import buncombe_elderly as m

ROW = {
    "pin": "9600000099", "owner": "TEST OWNER", "Address": "1 TEST LN", "CityName": "ASHEVILLE",
    "State": "NC", "Zipcode": "28801", "TotalMarketValue": "200000", "TaxValue": "200000",
    "Class": "100", "Exempt": "ELD", "CareOf": "",
    "SalePrice": None, "DeedDate": "", "DeedBook": "", "DeedPage": "", "Instrument": "",
}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Ctx:
    """Stands in for the `async with client(timeout=...) as c:` context manager."""

    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal) page."""

    def __init__(self, fail_times: int, exc=None, page=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self.page = page if page is not None else {"features": []}

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.page)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _run_fetch(http):
    s = m.BuncombeElderly()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        m.client = original


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, page={"features": [{"attributes": ROW}]})
    out = _run_fetch(http)
    assert http.calls == 3
    assert len(out) == 1
    assert out[0].owner_name == "TEST OWNER"


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"),
                       page={"features": [{"attributes": ROW}]})
    out = _run_fetch(http)
    assert http.calls == 2
    assert len(out) == 1


def test_a_connect_timeout_that_never_clears_still_gives_up_not_hangs():
    """fetch() has its own page-level `except Exception: break`, so the
    exhausted-retry error doesn't propagate out of fetch() -- but it must stop
    after the retry budget (stop_after_attempt(3)), not hang forever, and the
    scrape must come back as an (empty) result rather than crash the runner."""
    http = _FlakyHttp(fail_times=99)
    out = _run_fetch(http)
    assert http.calls == 3   # stop_after_attempt(3), then gives up
    assert out == []


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    out = _run_fetch(http)
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert out == []
