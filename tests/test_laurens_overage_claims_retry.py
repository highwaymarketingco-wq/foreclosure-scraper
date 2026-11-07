"""laurens_overage_claims.fetch: a transient transport error on the overage-PDF fetch gets
retried, not treated as "the whole scrape failed."

This file makes exactly one load-bearing network call -- the Treasurer's live overage-list
PDF, the one document the entire scrape's row count depends on. (Hub-page discovery at
_discover_doc_url() is a separate, already soft-fail-by-design call: on any failure it falls
back to FALLBACK_DOC_URL, a hardcoded live-verified URL, so a blip there never zeroes the
scrape -- out of scope here, confirmed by inspection.) The doc fetch was a bare `c.get()`
inside a bare `try/except Exception: return out` with zero retry cushioning: a single
transient blip (a connection reset, a timeout) permanently zeroed this scrape's whole result
for the run, reported as a healthy empty result, with no fallback date window to self-heal
later (this slug is registered in main.DATELESS_OK_SOURCES -- see the file's own sale_date
comment, and test_laurens_overage_claims.py::test_slug_is_dateless_whitelisted). Same gap
already fixed tonight for the Column legal-notice API scrapers, spartan_weekly_legals.py,
oconee_tax_sale.py, york_overage_claims.py, and the shared arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import laurens_overage_claims as M

#: The hub page's own fetch always succeeds cleanly here with no matching "Overage List"
#: anchor, so _discover_doc_url() falls through to FALLBACK_DOC_URL on every test below --
#: hub discovery has its own independent soft-fail design and is not the call under test.
_HUB_PAGE = b"<html><body><p>no matching link on this page</p></body></html>"


def _resp(url: str, status_code: int = 200, content: bytes = b"") -> httpx.Response:
    """A real httpx.Response (not a MagicMock) so raise_for_status() behaves exactly as it
    does in production -- a MagicMock's raise_for_status() is itself just a mock and would
    never actually raise for a bad status code."""
    return httpx.Response(status_code, content=content, request=httpx.Request("GET", url))


def _fake_async_client(get_handler):
    """Stands in for `httpx.AsyncClient(...)` itself -- this file builds its own client
    inline (`async with httpx.AsyncClient(...) as c:`) rather than going through a shared
    client() helper, so the fake has to replace the constructor, not a module-level name."""

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            stub = type("Stub", (), {})()
            stub.get = get_handler
            return stub

        async def __aexit__(self, *exc_info):
            return False

    return _FakeAsyncClient


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, timeout=None):
        if url == M.HUB_URL:
            return _resp(url, 200, _HUB_PAGE)
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _resp(url, 200, b"not actually a pdf")  # short-circuits at the not_pdf check

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(get))
    rows = list(asyncio.run(M.LaurensOverageClaims().fetch()))
    assert calls["n"] == 3          # 2 failures + 1 success -- proves the retry cushioning ran
    assert rows == []               # non-PDF body after the retry succeeds, handled normally


def test_a_transient_error_that_never_clears_still_ends_cleanly_not_an_infinite_hang(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, timeout=None):
        if url == M.HUB_URL:
            return _resp(url, 200, _HUB_PAGE)
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(get))
    rows = list(asyncio.run(M.LaurensOverageClaims().fetch()))
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up -- not an infinite hang
    assert rows == []        # fetch()'s own pre-existing bare except still swallows to [],
                              # exactly as before the fix, just only after 3 real attempts


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, timeout=None):
        if url == M.HUB_URL:
            return _resp(url, 200, _HUB_PAGE)
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return _resp(url, 200, b"not actually a pdf")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(get))
    rows = list(asyncio.run(M.LaurensOverageClaims().fetch()))
    assert calls["n"] == 2
    assert rows == []


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, timeout=None):
        if url == M.HUB_URL:
            return _resp(url, 200, _HUB_PAGE)
        calls["n"] += 1
        return _resp(url, 503, b"")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(get))
    rows = list(asyncio.run(M.LaurensOverageClaims().fetch()))
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []
