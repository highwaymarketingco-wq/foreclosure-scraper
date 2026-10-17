"""sheriff_sales._fetch_html: a transient transport error on a county-page fetch
gets retried, not treated as "the whole county's scrape failed."

Found 2026-10-17 (unprotected-network-call audit): `_fetch_html` called the shared
`http_client.client()` context manager directly with zero retry wrapper of its own,
bypassing `http_client.get_text()` (which DOES retry) entirely. `client()`'s own
module comment says plainly: "retries=0 removes the transport's connect-retry
amplification -- callers already wrap their own AsyncRetrying." Both call sites in
`_fetch_county` (the main per-county page fetch at the top, and the sub-page loop)
route through this one function, so a single transient connection-reset/timeout
used to permanently zero that county's entire scrape for the run -- and since
`national.sheriff_sales` carries no fallback date window (dateless source), a
zeroed run could not self-heal, it just silently reported an empty/healthy result.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import http_client
from foreclosure_scraper.scrapers.national import sheriff_sales as ss

URL = "https://www.brunswicksheriff.com/resources/auctions"


class _FakeResp:
    def __init__(self, text: str = "<html>ok</html>", status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"bad status {self.status_code}", request=request, response=response
            )


class _FakeAsyncClient:
    """Stands in for the `httpx.AsyncClient` yielded by `http_client.client()`."""

    def __init__(self, flaky: "_FlakyHttp"):
        self._flaky = flaky

    async def get(self, url, *args, **kwargs):
        return await self._flaky._get(url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (terminal) response."""

    def __init__(self, fail_times: int, exc=None, final_status: int = 200,
                 final_text: str = "<html>ok</html>"):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.final_status = final_status
        self.final_text = final_text
        self.calls = 0

    async def _get(self, url):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.final_text, self.final_status)

    def client_factory(self, *, timeout=30.0, **kwargs):  # noqa: ARG002
        return _FakeAsyncClient(self)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same technique as the arcgis_webmap reference test: make tenacity's
    # exponential-jitter backoff effectively instant in tests.
    monkeypatch.setattr(
        ss, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def _patch_client(monkeypatch, flaky: _FlakyHttp):
    # `_fetch_html` does `from ...http_client import client` INSIDE the function
    # body, so patching the name on the `http_client` module (not on `ss`) is what
    # actually takes effect at call time.
    monkeypatch.setattr(http_client, "client", flaky.client_factory)


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    flaky = _FlakyHttp(fail_times=2)
    _patch_client(monkeypatch, flaky)
    html = asyncio.run(ss._fetch_html(URL, timeout=30.0))
    assert flaky.calls == 3
    assert html == "<html>ok</html>"


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    flaky = _FlakyHttp(fail_times=99)
    _patch_client(monkeypatch, flaky)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(ss._fetch_html(URL, timeout=30.0))
    assert flaky.calls == 3  # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried(monkeypatch):
    flaky = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    _patch_client(monkeypatch, flaky)
    html = asyncio.run(ss._fetch_html(URL, timeout=30.0))
    assert flaky.calls == 2
    assert html == "<html>ok</html>"


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    flaky = _FlakyHttp(fail_times=0, final_status=404)
    _patch_client(monkeypatch, flaky)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(ss._fetch_html(URL, timeout=30.0))
    assert flaky.calls == 1  # a real bad status is not a transport/timeout error


def test_a_plain_timeout_error_is_also_retried(monkeypatch):
    # TimeoutError (not just httpx's TimeoutException) is in the retry predicate.
    flaky = _FlakyHttp(fail_times=1, exc=TimeoutError("socket timed out"))
    _patch_client(monkeypatch, flaky)
    html = asyncio.run(ss._fetch_html(URL, timeout=30.0))
    assert flaky.calls == 2
    assert html == "<html>ok</html>"
