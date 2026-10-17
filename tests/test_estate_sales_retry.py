"""national.estate_sales._fetch_text: a transient transport/timeout error on
the underlying http_client.client() GET gets retried, not treated as "this
zip's (or this listing's) whole fetch failed."

Found 2026-10-17 (gap-sweep follow-up): _fetch_text() wraps http_client's
shared, throttled `client()` context manager directly -- `async with
client(timeout=timeout, headers=h) as c: r = await c.get(url)` -- instead of
going through the project's already-retried `get_text()` helper. client()'s
own transport is explicitly built with `httpx.AsyncHTTPTransport(retries=0)`;
its docstring says callers must wrap their own AsyncRetrying. _fetch_text()
never did, so a single transient connect/read blip would zero out whichever
call site invoked it: once per SEARCH_ZIPS zip code in
_fetch_estatesales_net(), or once per listing in
_enrich_estatesales_net_gallery(). Both call sites are registered in
main.DATELESS_OK_SOURCES (no fallback date window), so a zeroed run can't
self-heal later. Same bug shape already fixed tonight in the Column
legal-notice API scraper, spartan_weekly_legals.py, and
arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import http_client
from foreclosure_scraper.scrapers.national import estate_sales as m

URL = "https://www.estatesales.net/NC/Asheville/"


class _FakeResp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=response
            )


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal) response."""

    def __init__(self, fail_times: int, exc=None, status_code: int = 200,
                 text: str = "<html>ok</html>"):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self.status_code = status_code
        self.text = text

    async def get(self, url):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.status_code, self.text)


def _fake_client_factory(http):
    """Stand-in for http_client.client(): yields `http` instead of a real
    throttled httpx.AsyncClient, same async-context-manager shape _fetch_text
    uses (`async with client(timeout=..., headers=...) as c`)."""
    @asynccontextmanager
    async def _client(*, timeout=30.0, headers=None):
        yield http
    return _client


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(fail_times=2)
    monkeypatch.setattr(http_client, "client", _fake_client_factory(http))

    text = asyncio.run(m._fetch_text(URL))
    assert http.calls == 3
    assert text == "<html>ok</html>"


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    http = _FlakyHttp(fail_times=99)
    monkeypatch.setattr(http_client, "client", _fake_client_factory(http))

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(m._fetch_text(URL))
    assert http.calls == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(http_client, "client", _fake_client_factory(http))

    text = asyncio.run(m._fetch_text(URL))
    assert http.calls == 2
    assert text == "<html>ok</html>"


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    http = _FlakyHttp(fail_times=0, status_code=503, text="")
    monkeypatch.setattr(http_client, "client", _fake_client_factory(http))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(m._fetch_text(URL))
    assert http.calls == 1   # a real bad status is not a transport/timeout error


def test_a_404_is_not_retried_either(monkeypatch):
    http = _FlakyHttp(fail_times=0, status_code=404, text="")
    monkeypatch.setattr(http_client, "client", _fake_client_factory(http))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(m._fetch_text(URL))
    assert http.calls == 1
