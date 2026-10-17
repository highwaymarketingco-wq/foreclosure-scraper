"""transylvania_vacant.TransylvaniaVacant.fetch: a transient transport/timeout error on the
ArcGIS page fetch gets retried, not treated as "the whole scrape failed."

Found 2026-10-17 (gap-sweep investigation): the pagination loop's only network call --
``r = await c.get(QUERY_URL, params=params)`` -- went through the shared, throttled
``client()`` helper directly with zero retry cushioning, guarded only by a bare
``except Exception: break``. The helper's own docstring says callers must wrap their own
AsyncRetrying; this module never did. Because every page (including the FIRST, offset=0,
which runs on every single invocation) appends to one shared ``out`` list, a transient
blip could zero the whole run's output (if it hit page 1) or silently truncate it (if it
hit a later page) -- reported as a healthy result either way, since this scraper is
registered in main.DATELESS_OK_SOURCES (no fallback date window to self-heal from). Same
root cause, same fix, already shipped tonight for the Column legal-notice API scrapers,
spartan_weekly_legals.py, the shared arcgis_webmap.query_features(), and gaston_vacant.py.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import transylvania_vacant as m

ONE_FEATURE_PAGE = {"features": [{
    "attributes": {"PIN": "TESTPIN1", "OWNER_NAME": "TEST OWNER", "LEGAL_ADDR": "CASHIERS RD"},
}]}
EMPTY_PAGE = {"features": []}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal, single-page) response."""

    def __init__(self, fail_times: int, exc=None, final_payload=None, final_status=200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.final_payload = final_payload if final_payload is not None else EMPTY_PAGE
        self.final_status = final_status
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.final_payload, self.final_status)


class _Ctx:
    """Stands in for the ``async with client(...) as c:`` block."""

    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(http):
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(m.TransylvaniaVacant().fetch())
    finally:
        m.client = original


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 3
    assert len(out) == 1
    assert out[0].parcel_id == "TESTPIN1"
    assert out[0].owner_name == "TEST OWNER"


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"), final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 2
    assert len(out) == 1


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99)  # always raises
    with pytest.raises(httpx.ConnectTimeout):
        _run_fetch(http)
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- the exception now
                              # surfaces instead of being silently swallowed into a break


def test_a_real_bad_http_status_is_not_retried():
    http = _FlakyHttp(fail_times=0, final_status=503, final_payload={})
    out = _run_fetch(http)
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert out == []
