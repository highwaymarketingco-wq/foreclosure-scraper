"""nc_coastal_tax_foreclosure._resolve_onemap: a transient transport/timeout error
on the NC OneMap ArcGIS parcel-lookup call gets retried, not treated as a dead
listing with zero self-healing.

Found 2026-10-16 (gap-sweep follow-up audit): _resolve_onemap takes a raw
httpx.AsyncClient from the shared http_client.client() context manager (NOT
get_text/get_bytes) and did a bare `await c.get(...)` with zero retry
wrapper. client()'s own docstring is explicit that it does not retry on the
caller's behalf ("retries=0 removes the transport's connect-retry
amplification — callers already wrap their own AsyncRetrying"), but
_resolve_onemap never did that wrapping: it only had
`except (httpx.HTTPError, ValueError): continue`, which just moves on to the
other field name (parno -> altparno) with no backoff at all. A single
connection reset or timeout on this per-listing ArcGIS FeatureServer call
permanently failed that listing's enrichment (no lat/lng/owner/address/value
fill), and for a Brunswick row -- whose own parser never has a street address
-- OneMap is the ONLY source of that data, so a transient miss could silently
fail the oceanfront scope gate later with no self-healing. Same root cause
already fixed tonight for the Column legal-notice API scrapers,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features()
function.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import nc_coastal_tax_foreclosure as mod

PARCEL = "036764"
COUNTY = "Brunswick"

_GOOD_PAYLOAD = {
    "features": [
        {
            "attributes": {"parno": PARCEL, "siteadd": "100 Main St", "ownname": "DOE JOHN"},
            "geometry": {"x": -78.0, "y": 34.0},
        }
    ]
}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyClient:
    """Raises on the first N calls, then serves a real response."""

    def __init__(self, fail_times: int, exc=None, payload=None, status_code=200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.payload = payload if payload is not None else _GOOD_PAYLOAD
        self.status_code = status_code
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.payload, self.status_code)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same trick as the arcgis_webmap reference test: patch the module-level
    # name _resolve_onemap calls at invocation time, so the test doesn't
    # actually sleep through exponential backoff.
    monkeypatch.setattr(
        mod, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    client = _FlakyClient(fail_times=2)
    attrs = asyncio.run(mod._resolve_onemap(client, PARCEL, COUNTY))
    assert client.calls == 3  # 2 failures + 1 success, all on the "parno" field
    assert attrs is not None
    assert attrs["_centroid"] == (34.0, -78.0)


def test_a_read_timeout_is_also_retried():
    client = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    attrs = asyncio.run(mod._resolve_onemap(client, PARCEL, COUNTY))
    assert client.calls == 2
    assert attrs is not None


def test_a_connect_timeout_that_never_clears_is_bounded_not_hanging():
    client = _FlakyClient(fail_times=99)
    attrs = asyncio.run(mod._resolve_onemap(client, PARCEL, COUNTY))
    # stop_after_attempt(3) exhausts on "parno" and AsyncRetrying reraises; the
    # pre-existing `except (httpx.HTTPError, ValueError): continue` (unchanged
    # by this fix) catches that reraise and falls through to "altparno", which
    # also exhausts its own 3 attempts. 6 calls total -- a bounded, finite
    # retry budget, never an unbounded retry storm or a hang.
    assert client.calls == 6
    assert attrs is None


def test_a_real_http_status_error_is_not_retried():
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                "500", request=req, response=httpx.Response(500, request=req)
            )

    client = _BadStatusClient()
    attrs = asyncio.run(mod._resolve_onemap(client, PARCEL, COUNTY))
    # httpx.HTTPStatusError is not httpx.TransportError/TimeoutException, so
    # the retry predicate rejects it -- exactly one call per field (no
    # backoff), not three.
    assert client.calls == 2
    assert attrs is None


def test_a_non_200_status_response_is_not_retried():
    """A plain non-200 response (no exception raised at all) was already
    handled by the pre-existing status check -- confirm the new retry
    wrapper doesn't change that (nothing to retry: no exception is raised)."""
    client = _FlakyClient(fail_times=0, status_code=503)
    attrs = asyncio.run(mod._resolve_onemap(client, PARCEL, COUNTY))
    assert client.calls == 2  # one per field; a non-exception bad status never retries
    assert attrs is None


def test_no_features_found_falls_through_without_retrying():
    client = _FlakyClient(fail_times=0, payload={"features": []})
    attrs = asyncio.run(mod._resolve_onemap(client, PARCEL, COUNTY))
    assert client.calls == 2
    assert attrs is None
