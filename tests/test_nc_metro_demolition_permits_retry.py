"""nc_metro_demolition_permits._cary_rows: a transient transport error on the Cary
OpenDataSoft page fetch gets retried, not treated as "the whole feed failed."

Found 2026-11-07 (production-bug audit): of this file's two network call sites, only the
three ArcGIS feeds (mecklenburg/greensboro/durham) are retry-protected, via fetch_attrs ->
arcgis_webmap.query_features's own AsyncRetrying (see test_arcgis_webmap_query_features_retry.py).
The cary feed's `_cary_rows` hits Cary's OpenDataSoft REST API directly with a bare `c.get()`
and had zero retry cushioning of its own -- the same root cause already fixed for
arcgis_webmap.query_features, the Column legal-notice API scrapers, and
spartan_weekly_legals.py (http_client-style callers must wrap their own AsyncRetrying; this
call site never did). LayerHarvest's own 2-try backstop (layer_guard.py) is not a substitute:
its docstring says it exists because callers are EXPECTED to already retry themselves, and
its `except Exception` clause would also burn one of its two tries retrying a genuine
bad-status RuntimeError rather than a transient blip. Because this slug is in
main.DATELESS_OK_SOURCES (no sale/issue date to fall back on), a single transient network
blip that survives LayerHarvest's one spare retry silently zeros all of Cary's
demolition-permit leads for the run, reported as a healthy empty result.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.counties_nc.nc_metro_demolition_permits as m

CARY_FEED = next(f for f in m.FEEDS if f.name == "cary")

#: A real-shaped Cary OpenDataSoft row (trimmed to the fields this module reads).
CARY_ROW = {
    "permitnum": "26-00001000", "applieddate": "2026-09-01", "issuedate": "2026-09-05",
    "statuscurrent": "ISSUED", "originaladdress1": "50 CHAPEL HILL RD",
    "originalcity": "CARY", "originalzip": "27511", "pin": "761399999",
    "permittypedesc": "BLDG - DEMOLISH - SNGL FAM HOME (B645)",
    "ownername": "ROE ANN", "owneraddress1": "50 CHAPEL HILL RD", "ownerzip": "27511",
}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal, single-page) result."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"results": [CARY_ROW], "total_count": 1})


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    rows = asyncio.run(m._cary_rows(http, CARY_FEED, None))
    assert http.calls == 3
    assert rows == [CARY_ROW]


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(m._cary_rows(http, CARY_FEED, None))
    assert http.calls == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = asyncio.run(m._cary_rows(http, CARY_FEED, None))
    assert http.calls == 2
    assert rows == [CARY_ROW]


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    with pytest.raises(RuntimeError, match="cary: HTTP 503"):
        asyncio.run(m._cary_rows(http, CARY_FEED, None))
    assert http.calls == 1   # a real bad status is not a transport/timeout error -- never retried


def test_a_normal_empty_terminal_page_is_not_mistaken_for_a_failure():
    """Not a transient failure at all -- a legitimately empty/terminal page must return
    immediately with one call, proving the retry wrapper only engages on a real
    transport/timeout error and never on ordinary pagination end-of-data."""
    class _EmptyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({"results": [], "total_count": 0})

    http = _EmptyHttp()
    rows = asyncio.run(m._cary_rows(http, CARY_FEED, None))
    assert http.calls == 1
    assert rows == []
