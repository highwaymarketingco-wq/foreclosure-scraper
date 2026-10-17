"""SCUstRegistry.fetch: the one-off "seed the session" GET must not be a bare,
unretried single point of failure for the whole 46-county run.

Found 2026-10-17: `await c.get(BASE)` at the top of `fetch()` ran once per run,
BEFORE the per-county loop starts and before `guard = LayerHarvest(...)` even
opens -- completely outside LayerHarvest's own attempts=3 retry, which only
covers the per-county search POST in `_one_county`. http_client.client()'s
transport is built with retries=0 ("callers already wrap their own
AsyncRetrying"), so this bare call had zero retry cushioning: a single
transient connection reset or timeout raised straight out of fetch() and
zeroed ALL 46 counties' worth of leads for the run, not just one county.
Because this source is registered in main.DATELESS_OK_SOURCES, a zeroed run
has no fallback date window to self-heal on later -- the same bug shape
already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.counties_sc.sc_ust_registry as sc


class _FakeResp:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FakeHttp:
    """Fake http_client.client() session. ``.get`` is the flaky session-seed
    call under test; ``.post`` is the per-county search -- always a clean,
    empty 200 page, so the per-county loop (outside this bug's scope) never
    itself fails or retries."""

    def __init__(self, get_impl):
        self._get_impl = get_impl
        self.get_calls = 0
        self.post_calls = 0

    async def get(self, url):
        self.get_calls += 1
        return await self._get_impl()

    async def post(self, url, data=None, timeout=None):
        self.post_calls += 1
        return _FakeResp(text="", status_code=200)


def _flaky_get(fail_times: int, exc: Exception | None = None):
    """Raises ``exc`` on the first ``fail_times`` calls, then succeeds."""
    exc = exc or httpx.ConnectTimeout("boom")
    calls = {"n": 0}

    async def _get():
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc
        return None  # fetch() discards the seed GET's response either way

    return _get


def _always_raise(exc: Exception):
    async def _get():
        raise exc

    return _get


def _client_factory(fake_http: _FakeHttp):
    @asynccontextmanager
    async def _client(*args, **kwargs):
        yield fake_http

    return _client


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(sc, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _one_fake_county_no_env_kill_switch(monkeypatch):
    # A single declared layer keeps LayerHarvest happy (it refuses an empty
    # layer set) without actually looping all 46 real counties for this
    # narrowly-scoped retry test.
    monkeypatch.setattr(sc, "COUNTIES", ("Test County",))
    monkeypatch.delenv("FORECLOSURE_SC_UST", raising=False)


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _FakeHttp(_flaky_get(fail_times=2))
    monkeypatch.setattr(sc, "client", _client_factory(http))

    rows = asyncio.run(sc.SCUstRegistry().fetch())

    assert http.get_calls == 3
    assert rows == []
    assert http.post_calls == 1  # seeding cleared, so the per-county loop still ran


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    http = _FakeHttp(_flaky_get(fail_times=99))
    monkeypatch.setattr(sc, "client", _client_factory(http))

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(sc.SCUstRegistry().fetch())

    assert http.get_calls == 3  # stop_after_attempt(3), then gives up
    assert http.post_calls == 0  # never even reached the per-county loop


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FakeHttp(_flaky_get(fail_times=1, exc=httpx.ReadTimeout("slow")))
    monkeypatch.setattr(sc, "client", _client_factory(http))

    rows = asyncio.run(sc.SCUstRegistry().fetch())

    assert http.get_calls == 2
    assert rows == []


def test_a_real_non_transport_error_is_not_retried(monkeypatch):
    """This bare seed GET never itself checks the response status (its result
    is discarded), so there is no literal "non-200" branch to exercise here --
    but the retry classification itself must still only catch transport/timeout
    errors. Stand in with an httpx.HTTPStatusError (the real-bad-HTTP-status
    exception type elsewhere in this codebase), which is NOT in the
    retry_if_exception_type tuple, and confirm it fails on attempt 1."""
    request = httpx.Request("GET", sc.BASE)
    response = httpx.Response(500, request=request)
    exc = httpx.HTTPStatusError("500 Server Error", request=request, response=response)
    http = _FakeHttp(_always_raise(exc))
    monkeypatch.setattr(sc, "client", _client_factory(http))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(sc.SCUstRegistry().fetch())

    assert http.get_calls == 1  # a real bad status is not a transport/timeout error
    assert http.post_calls == 0
