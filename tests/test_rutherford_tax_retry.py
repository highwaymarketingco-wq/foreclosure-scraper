"""rutherford_tax._pin_map: a transient transport error on a page fetch gets retried,
not treated as "pagination over, keep whatever you have."

Found 2026-10-17 (gap-sweep): _pin_map()'s single `http.get()` call on the county's
ArcGIS parcel layer had zero retry cushioning -- the exact same gap already fixed
tonight for the Column legal-notice API scrapers, spartan_weekly_legals.py and the
shared arcgis_webmap.query_features(). The surrounding try/except logs and `break`s
the WHOLE ~29-page pagination on first failure, so one transient blip on page N loses
every page after it too, not just page N's rows. A real non-200 response (silently
turned into body={}, which also ends the loop two lines later) and an HTTP-200-with
-error-body response are both left exactly as before -- neither is a transport/timeout
error, so neither is retried.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import rutherford_tax as rt


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


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(rt, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))
    # _pin_map sleeps _PIN_PAGE_PAUSE_S between pages when offset > 0; these tests
    # never get past page 1 (the terminal empty page ends the loop), so no patch is
    # needed for that -- kept out to match the reference test file's minimalism.


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    pins = asyncio.run(rt._pin_map(http))
    assert http.calls == 3
    assert pins == {}


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    """Retries are exhausted inside _pin_map's own try/except, which logs and breaks --
    so the whole _pin_map() call still returns (whatever it has), never hangs and never
    raises out to the caller. This is the same give-up behavior as a non-transient
    failure (test_a_failed_pin_map_read_returns_what_it_has in test_rutherford_tax.py),
    just reached after stop_after_attempt(3) instead of on attempt 1."""
    http = _FlakyHttp(fail_times=99)
    pins = asyncio.run(rt._pin_map(http))
    assert pins == {}
    assert http.calls == 3   # stop_after_attempt(3), then the outer except gives up


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    pins = asyncio.run(rt._pin_map(http))
    assert http.calls == 2
    assert pins == {}


def test_a_real_non_200_status_is_not_retried():
    """A non-200 response doesn't raise at all in _pin_map -- `body` silently becomes
    {}, which fails the `isinstance(body, dict) and not body.get('error')` check's
    sibling (features ends up [] via body.get('features') or []) and the loop breaks
    on the next line. It must NOT be retried: a real bad status is not a transport
    error."""
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({"features": [{"attributes": {
                "Parcel_Number": "123456", "PIN": "1600000001"}}]}, status_code=503)

    http = _BadStatusHttp()
    pins = asyncio.run(rt._pin_map(http))
    assert pins == {}         # the 503's body (even though it has features) was never read
    assert http.calls == 1    # a real bad status is not a transport/timeout error


def test_a_200_with_an_error_body_is_not_retried():
    class _ErrorBodyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({"error": {"code": 400, "message": "layer unavailable"}})

    http = _ErrorBodyHttp()
    pins = asyncio.run(rt._pin_map(http))
    assert pins == {}
    assert http.calls == 1   # the classic HTTP-200-plus-error-body silent-death shape, unretried
