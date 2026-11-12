"""brunswick_legal_notices._resolve_onemap: a transient transport error on the NC OneMap
parcel-resolve call gets retried, not treated as "this listing can't be geo-enriched."

Found 2026-10-16/17 (gap-sweep follow-up): this call bypasses get_text/get_bytes and hits
the raw http_client.client() helper directly. That helper's own transport sets retries=0
and its docstring says callers must wrap their own AsyncRetrying -- this file never did.
The only error handling was `except (httpx.HTTPError, ValueError): continue`, which on a
transient blip just gives up on the current field name (parno/altparno) and falls through
to the next one rather than retrying the same request with backoff; if both field attempts
hit a transient blip the function silently returns None, dropping that one listing's
lat/lng/owner/value instead of a single transient network hiccup being absorbed. Same root-
cause helper-contract gap already fixed tonight for a Column legal-notice API scraper,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features() function.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import brunswick_legal_notices as bln

LAYER = bln.ONEMAP_QUERY


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


_FEATURE_PAYLOAD = {
    "features": [
        {
            "attributes": {"parno": "173BC001", "siteadd": "123 MAIN ST"},
            "geometry": {"x": -78.1, "y": 34.0},
        }
    ]
}


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (terminal) response."""

    def __init__(self, fail_times: int, exc=None, payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.payload = payload if payload is not None else _FEATURE_PAYLOAD
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.payload)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        bln, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    attrs = asyncio.run(bln._resolve_onemap(http, "173BC001"))
    # First field attempt ("parno") eats the retries and then succeeds -- no need to
    # fall through to "altparno".
    assert http.calls == 3
    assert attrs is not None
    assert attrs["_centroid"] == (34.0, -78.1)


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs_and_returns_none():
    http = _FlakyHttp(fail_times=99)
    attrs = asyncio.run(bln._resolve_onemap(http, "173BC001"))
    # stop_after_attempt(3) per field attempt, then the exhausted-retry exception is
    # caught by the function's own `except (httpx.HTTPError, ValueError): continue` and
    # it falls through to the next field name -- so both "parno" and "altparno" each
    # burn their own 3 attempts (6 total) rather than hanging forever, and the function
    # returns None instead of raising or hanging.
    assert http.calls == 6
    assert attrs is None


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    attrs = asyncio.run(bln._resolve_onemap(http, "173BC001"))
    assert http.calls == 2
    assert attrs is not None


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    attrs = asyncio.run(bln._resolve_onemap(http, "173BC001"))
    # A real bad status is not a transport/timeout error, so it is not retried -- the
    # function just treats it as "no result for this field" (status != 200 -> continue)
    # and moves straight to the next field name, one call each.
    assert http.calls == 2
    assert attrs is None


def test_a_200_with_an_error_body_is_not_retried():
    class _ErrorBodyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({"error": {"code": 400, "message": "layer unavailable"}})

    http = _ErrorBodyHttp()
    attrs = asyncio.run(bln._resolve_onemap(http, "173BC001"))
    # The classic HTTP-200-plus-error-body silent-death shape: not a transport/timeout
    # error, so unretried -- one call per field name.
    assert http.calls == 2
    assert attrs is None
