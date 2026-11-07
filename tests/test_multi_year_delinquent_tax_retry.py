"""counties_generic.multi_year_delinquent_tax._get_json: a transient transport error on
the ONE network call in this file gets retried, not treated as "the whole result is empty."

_get_json is the only real network call in multi_year_delinquent_tax.py -- every other
function (_list_services, _resolve_layer, _distinct, _fetch_layer's per-page pagination
loop) funnels through it. It had zero retry cushioning: no tenacity import anywhere in
the file, and the shared http_client.client() transport deliberately sets retries=0
("callers already wrap their own AsyncRetrying"). This file also does NOT import the
shared arcgis_webmap module, so that module's already-fixed query_features() gave it no
inherited protection -- it rolls its own separate, still-bare ArcGIS plumbing. A single
transient blip (a connection reset, a timeout) permanently empties whatever that call was
for -- an entire county's layer discovery (_list_services is called once per county), or
an entire year's roll mid-pagination (_fetch_layer's loop) -- and because
counties.multi_year_delinquent_tax is dateless (main.DATELESS_OK_SOURCES, no fallback
date window), that loss cannot self-heal on a later run; the next run just re-discovers
current state and silently "succeeds" with that chunk permanently missing.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_generic import (
    multi_year_delinquent_tax as myd,
)

URL = "https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/DT2025/FeatureServer/0/query"


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


class _FlakyHttp:
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


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Make the backoff wait near-instant so the exhausted-retry test doesn't
    actually sleep through stop_after_attempt(3)'s real exponential delay."""
    monkeypatch.setattr(
        myd, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    data = asyncio.run(myd._get_json(http, URL, {"f": "json"}))
    assert http.calls == 3
    assert data == {"features": []}


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(myd._get_json(http, URL, {"f": "json"}))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- no infinite hang


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    data = asyncio.run(myd._get_json(http, URL, {"f": "json"}))
    assert http.calls == 2
    assert data == {"features": []}


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(myd._get_json(http, URL, {"f": "json"}))
    assert http.calls == 1   # a real bad status is not a transport/timeout error


def test_a_200_with_an_error_body_is_not_retried():
    """ArcGIS's classic silent-death shape: HTTP 200 with an {"error": ...} body.
    _get_json raises ValueError for this (see module docstring reference to
    project_column_source_silent_death) -- it must never be retried either,
    since retrying a real error-body response just burns the budget on a
    request that will never succeed."""
    class _ErrorBodyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            return _FakeResp({"error": {"code": 400, "message": "layer unavailable"}})

    http = _ErrorBodyHttp()
    with pytest.raises(ValueError):
        asyncio.run(myd._get_json(http, URL, {"f": "json"}))
    assert http.calls == 1   # the classic HTTP-200-plus-error-body silent-death shape, unretried
