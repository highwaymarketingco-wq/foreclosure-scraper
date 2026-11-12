"""YorkOverageClaims.fetch: a transient transport/timeout error on either of its two PDF
download attempts (curl_cffi first, httpx fallback second) gets retried, not treated as
"the whole scrape's result is zero for this run."

Found 2026-11-07, same bug shape already fixed tonight for the Column legal-notice API
scrapers, spartan_weekly_legals.py, and the shared arcgis_webmap.query_features(): both
download attempts inside fetch() -- curl_cffi (chrome-impersonate, defeats Cloudflare)
tried first, httpx with a full browser UA tried second -- had zero retry cushioning on
their network call. counties_sc.york_overage_claims is listed in main.DATELESS_OK_SOURCES
(the overage claim is a standing condition, not a scheduled event, so there is no fallback
date window), so a single transient blip hitting both back-to-back attempts in the same
run used to permanently zero this scrape's whole result, reported as a healthy empty run.

Both legs are now wrapped in the same proven AsyncRetrying pattern: retry only a transport
or timeout error, up to 3 attempts with short exponential-jitter backoff, reraise after the
budget is exhausted. Neither leg's actual request logic changed -- same URL, same headers,
same impersonate/timeout/redirect kwargs, same status-code/length checks.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from curl_cffi import requests as cc_requests
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import york_overage_claims as yoc

# A short, deliberately-not-a-real-PDF body. pypdf's PdfReader raises PdfStreamError on
# this almost instantly (verified directly: no hang), which fetch()'s existing try/except
# around PDF parsing already turns into a clean, empty-list return -- the exact same
# return value a successfully-parsed-but-record-less real PDF would also produce. Retry
# correctness (what this file tests) does not depend on the body actually being a real PDF.
_FAKE_PDF_BODY = b"%PDF-not-real" + b"x" * 1100


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same technique as test_arcgis_webmap_query_features_retry.py: patch the name the
    module under test calls at retry-construction time so the real exponential-jitter
    backoff (initial=1, max=8) never actually makes this test suite wait seconds."""
    monkeypatch.setattr(yoc, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _scraper() -> yoc.YorkOverageClaims:
    return yoc.YorkOverageClaims()


def _patch_httpx(monkeypatch, handler):
    """Same technique already proven in test_sc_overage_full_user_agent.py's
    _patch_client: wrap the REAL httpx.AsyncClient so it is wired to
    httpx.MockTransport(handler). A handler that raises behaves exactly like a real
    transport failure -- a genuine httpx exception propagates, not a hand-rolled stand-in
    (verified directly: MockTransport propagates a handler's raised exception unchanged)."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _curl_cffi_always_fails(monkeypatch):
    """Force the curl_cffi leg to fail immediately (a RequestsError, same family the fix
    retries) so every httpx-leg test below deterministically reaches the fallback --
    mirrors _patch_client's own guard against curl_cffi succeeding for real."""

    def _always_fails(*_a, **_kw):
        raise cc_requests.RequestsError("curl_cffi disabled in this test")

    monkeypatch.setattr(cc_requests, "get", _always_fails)


class _FlakyCurlGet:
    """Stand-in for curl_cffi's module-level `requests.get`: raises on the first
    `fail_times` calls, then returns a response that satisfies fetch()'s
    `status_code == 200 and len(content) > 1000` success check."""

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    def __call__(self, url, headers=None, impersonate=None, timeout=None, allow_redirects=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc or cc_requests.RequestsError("boom")

        class _Resp:
            status_code = 200
            content = _FAKE_PDF_BODY

        return _Resp()


# ---------------------------------------------------------------------------
# Leg 1: curl_cffi -- sync call, wrapped without `await` per the fix (curl_cffi's
# module-level `.get` is not awaitable in this sync-import form).
# ---------------------------------------------------------------------------

def test_curl_cffi_transient_error_is_retried_and_then_succeeds(monkeypatch):
    fake_curl = _FlakyCurlGet(fail_times=2)
    monkeypatch.setattr(cc_requests, "get", fake_curl)

    def httpx_poison(request: httpx.Request) -> httpx.Response:
        raise AssertionError("curl_cffi succeeded -- httpx fallback should never be reached")
    _patch_httpx(monkeypatch, httpx_poison)

    listings = asyncio.run(_scraper().fetch())
    assert fake_curl.calls == 3
    assert listings == []  # fake body has no parseable records; retry count is what matters


def test_curl_cffi_retry_exhausted_falls_through_to_httpx_without_hanging(monkeypatch):
    fake_curl = _FlakyCurlGet(fail_times=99)  # never clears within the retry budget
    monkeypatch.setattr(cc_requests, "get", fake_curl)

    httpx_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        httpx_calls["n"] += 1
        return httpx.Response(200, content=_FAKE_PDF_BODY)
    _patch_httpx(monkeypatch, handler)

    listings = asyncio.run(_scraper().fetch())
    assert fake_curl.calls == 3       # stop_after_attempt(3) on the curl_cffi leg, then gives up
    assert httpx_calls["n"] == 1      # falls through to httpx (unchanged existing behavior)
    assert listings == []


def test_curl_cffi_bad_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def bad_status_get(url, headers=None, impersonate=None, timeout=None, allow_redirects=None):
        calls["n"] += 1

        class _Resp:
            status_code = 403  # a real Cloudflare block -- not a transport/timeout error
            content = b"forbidden"

        return _Resp()
    monkeypatch.setattr(cc_requests, "get", bad_status_get)

    httpx_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        httpx_calls["n"] += 1
        return httpx.Response(200, content=_FAKE_PDF_BODY)
    _patch_httpx(monkeypatch, handler)

    asyncio.run(_scraper().fetch())
    assert calls["n"] == 1          # a real bad status never raises, so it is never retried
    assert httpx_calls["n"] == 1    # curl_cffi leg "failed" its own status/length check


# ---------------------------------------------------------------------------
# Leg 2: httpx fallback
# ---------------------------------------------------------------------------

def test_httpx_fallback_transient_error_is_retried_and_then_succeeds(monkeypatch):
    _curl_cffi_always_fails(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.ConnectTimeout("boom")
        return httpx.Response(200, content=_FAKE_PDF_BODY)
    _patch_httpx(monkeypatch, handler)

    listings = asyncio.run(_scraper().fetch())
    assert calls["n"] == 3
    assert listings == []


def test_httpx_fallback_retry_exhausted_raises_and_fetch_returns_empty_not_hang(monkeypatch):
    _curl_cffi_always_fails(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("boom")  # never clears within the retry budget
    _patch_httpx(monkeypatch, handler)

    listings = asyncio.run(_scraper().fetch())
    # stop_after_attempt(3), then AsyncRetrying reraises -- caught by fetch()'s own
    # unchanged try/except, which logs a warning and returns [] instead of hanging or
    # propagating.
    assert calls["n"] == 3
    assert listings == []


def test_httpx_fallback_bad_status_is_not_retried(monkeypatch):
    _curl_cffi_always_fails(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="server error")
    _patch_httpx(monkeypatch, handler)

    listings = asyncio.run(_scraper().fetch())
    assert calls["n"] == 1   # a real bad status never raises, so it is never retried
    assert listings == []
