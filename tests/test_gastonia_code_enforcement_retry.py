"""gastonia_code_enforcement: a transient transport error on a polygon-query or
session-handshake fetch gets retried, not treated as "the whole crawl failed."

Found 2026-11-07 (same bug shape swept across the repo tonight): this module's
`_query_bbox()` -- the sole mechanism that fetches every case in the city via
recursive quad-tree subdivision -- POSTed to `LocatorResultsPolygon` with zero
try/except and zero retry wrapper. Because the recursion has no per-call
isolation (an exception raised in any one call propagates up through every
ancestor `await`, aborting ALL remaining siblings/cousins in the traversal),
and because `BaseScraper.safe_run()` only ships `self.partial` on a *timeout*
(not on a plain `httpx.ConnectError`/`ReadError`/generic exception, which this
bare call would raise on a connection blip), a single transient network hiccup
anywhere in the ~60-100-request full-city crawl zeroed the ENTIRE run's
returned rows -- even with 1,000+ properties already collected. The one-shot
anonymous session-handshake `http.get(LOCATOR_URL)` in `fetch()` had the exact
same gap in its purest form: it fires once, before anything is in
`self.partial`, so an unretried blip there guarantees zero output every time.
Both are dateless (`counties_nc.gastonia_code_enforcement` is in
`main.DATELESS_OK_SOURCES`), so a zeroed run cannot self-heal via a later
run's date-window overlap -- it just silently reports an empty/healthy result
forever until someone notices by hand. Same root cause already fixed tonight
for the Column legal-notice API scrapers, spartan_weekly_legals.py, and the
shared `arcgis_webmap.query_features()` (see
`tests/test_arcgis_webmap_query_features_retry.py`, which this file mirrors).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import gastonia_code_enforcement as mod


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://devsvcs.gastonianc.gov/CodeEnforcement/LocatorResultsPolygon")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=response)


class _FlakyPostHttp:
    """Raises on the first N-1 `.post()` calls, then serves a real (empty,
    terminal -- below PAGE_CAP) leaf page, exactly like `_FlakyHttp` in the
    arcgis_webmap reference test."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def post(self, url, data=None, headers=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"LocationMarkers": []})


class _FakeClientCtx:
    """Stands in for the `async with client(timeout=...) as http:` block in
    `fetch()`, so the handshake-retry wrap can be exercised without any real
    network I/O."""

    def __init__(self, http):
        self._http = http

    async def __aenter__(self):
        return self._http

    async def __aexit__(self, *exc_info):
        return False


class _HandshakeFlakyHttp:
    """`.get()` (the session handshake) is flaky per `fail_times`; `.post()`
    (the polygon query `_query_bbox` issues right after) always serves an
    empty, terminal leaf so a successful run completes in exactly one call."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.get_calls = 0
        self.post_calls = 0

    async def get(self, url, headers=None):
        self.get_calls += 1
        if self.get_calls <= self.fail_times:
            raise self.exc
        return _FakeResp({})

    async def post(self, url, data=None, headers=None):
        self.post_calls += 1
        return _FakeResp({"LocationMarkers": []})


def _fake_client_factory(http):
    def _factory(**kw):
        return _FakeClientCtx(http)
    return _factory


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _enabled_env(monkeypatch):
    # Make sure neither env gate is accidentally "0" from the surrounding
    # environment/test session -- these tests want the real code path.
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    monkeypatch.delenv(mod.ENV_DESC_OFF, raising=False)


# --- _query_bbox(): the primary finding -----------------------------------

def test_query_bbox_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyPostHttp(fail_times=2)
    rows = asyncio.run(mod._query_bbox(http, 0.0, 100.0, 0.0, 100.0))
    assert http.calls == 3
    assert rows == []


def test_query_bbox_transient_error_that_never_clears_still_raises_not_hangs():
    http = _FlakyPostHttp(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(mod._query_bbox(http, 0.0, 100.0, 0.0, 100.0))
    assert http.calls == 3   # stop_after_attempt(3), then gives up


def test_query_bbox_read_timeout_is_also_retried():
    http = _FlakyPostHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = asyncio.run(mod._query_bbox(http, 0.0, 100.0, 0.0, 100.0))
    assert http.calls == 2
    assert rows == []


def test_query_bbox_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def post(self, url, data=None, headers=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(mod._query_bbox(http, 0.0, 100.0, 0.0, 100.0))
    assert http.calls == 1   # a real bad status is not a transport/timeout error


# --- fetch()'s one-shot session-handshake GET: the secondary finding -----
#
# This call's return value is never inspected (no `.raise_for_status()`, no
# parsing) -- it exists only to receive the anonymous ASP.NET session cookie
# before the real crawl starts -- so there is no analogous "real HTTP error
# status is not retried" case here the way there is for `_query_bbox`; the
# only way this call fails is a raised transport/timeout exception (retried)
# or some other raised exception (not retried, covered by the same
# `retry_if_exception_type` contract already proven against `_query_bbox`
# above). The two cases below are the ones that actually apply to this site.

def test_handshake_transient_error_is_retried_and_then_the_crawl_succeeds(monkeypatch):
    http = _HandshakeFlakyHttp(fail_times=2)
    monkeypatch.setattr(mod, "client", _fake_client_factory(http))
    scraper = mod.GastoniaCodeEnforcement()

    rows = asyncio.run(scraper.fetch())

    assert http.get_calls == 3
    assert http.post_calls == 1
    assert rows == []


def test_handshake_transient_error_that_never_clears_still_raises_not_hangs(monkeypatch):
    http = _HandshakeFlakyHttp(fail_times=99)
    monkeypatch.setattr(mod, "client", _fake_client_factory(http))
    scraper = mod.GastoniaCodeEnforcement()

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(scraper.fetch())

    assert http.get_calls == 3   # stop_after_attempt(3), then gives up
    assert http.post_calls == 0  # never got past the handshake -- confirms the
                                  # blast radius the module docstring describes:
                                  # a failure here happens before _query_bbox
                                  # (and therefore self.partial) is touched at all
