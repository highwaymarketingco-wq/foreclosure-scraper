"""arcgis_webmap.query_features: a transient transport error on a page fetch gets retried,
not treated as "the whole query failed."

Found 2026-10-16 (gap-sweep, pre-run gate's additions audit): 8 of the pipeline's
counties_generic.arcgis_distress.* / county-specific ArcGIS layer scrapers (Wake code cases,
Cumberland/Iredell delinquent tax, Kinston/Charlotte-metro demolitions, Mecklenburg/York
tax-foreclosure layers, Horry probate) were producing zero or below-floor rows. All of them
go through this one shared query_features() call, which had zero retry cushioning on its
page fetch -- the exact same root cause already fixed tonight for the Column legal-notice
API scrapers and spartan_weekly_legals.py (http_client-style callers must wrap their own
AsyncRetrying; this one never did). A single transient blip permanently zeroes a dateless
source's whole scrape (no date window to fall back on), reported as a healthy empty result.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import arcgis_webmap as agw

LAYER = "https://gisweb.example.test/arcgis/rest/services/Parcels/FeatureServer/0"


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (empty, terminal) page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"features": [], "exceededTransferLimit": False})

    async def post(self, url, data=None, timeout=None):
        return await self.get(url, params=data, timeout=timeout)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(agw, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    rows = asyncio.run(agw.query_features(http, LAYER, out_fields="PIN,OBJECTID"))
    assert http.calls == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(agw.query_features(http, LAYER, out_fields="PIN,OBJECTID"))
    assert http.calls == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = asyncio.run(agw.query_features(http, LAYER, out_fields="PIN,OBJECTID"))
    assert http.calls == 2
    assert rows == []


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

        async def post(self, url, data=None, timeout=None):
            return await self.get(url, params=data, timeout=timeout)

    http = _BadStatusHttp()
    with pytest.raises(agw.ArcGisError):
        asyncio.run(agw.query_features(http, LAYER, out_fields="PIN,OBJECTID"))
    assert http.calls == 1   # a real bad status is not a transport/timeout error


def test_a_200_with_an_error_body_is_not_retried():
    class _ErrorBodyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({"error": {"code": 400, "message": "layer unavailable"}})

        async def post(self, url, data=None, timeout=None):
            return await self.get(url, params=data, timeout=timeout)

    http = _ErrorBodyHttp()
    with pytest.raises(agw.ArcGisError):
        asyncio.run(agw.query_features(http, LAYER, out_fields="PIN,OBJECTID"))
    assert http.calls == 1   # the classic HTTP-200-plus-error-body silent-death shape, unretried
