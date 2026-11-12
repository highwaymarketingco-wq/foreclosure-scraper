"""counties_sc.orangeburg_overage_claims: both bare network call sites get
AsyncRetrying cushioning against a transient transport error or timeout.

Found 2026-11-07 (unprotected-network-call audit): this file builds its OWN
bare `httpx.AsyncClient` (not the shared `http_client.py` module, which wraps
its own retries internally) and never retries either of its two real `c.get()`
calls:

  * `_discover_new_docs()` (module-level helper) fetches the county's hub
    page to pick up a newly-posted overage-list year. One attempt, no retry --
    a transient blip silently defeats self-healing year discovery for the run
    (the function already swallows any failure into an empty list, so this is
    best-effort/supplementary, not a data-zeroing bug on its own).

  * `OrangeburgOverageClaims.fetch()`'s per-item loop fetches each year's
    actual document (PDF/xlsx) and is what produces the real Listing rows.
    One attempt, no retry -- a single connection reset/timeout permanently
    drops that year's whole roster for the run (`continue` to the next URL),
    and this slug carries no fallback date window
    (main.py.DATELESS_OK_SOURCES), so a dropped year cannot self-heal later.

Both call sites already wrap their own exceptions in a catch-log-and-continue/
return-empty block that this fix does not touch, so a retry-exhausted or
real-HTTP-error failure never escapes past that pre-existing boundary -- the
only externally observable proof the retry wrapper is doing its job (3
attempts on a transient error, 1 attempt on a real bad status, no hang) is
the fake client's own call count, which is what every test below asserts on.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import orangeburg_overage_claims as ooc

DOC_URL = "https://example.test/DocumentCenter/View/9999"


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same technique as the arcgis_webmap reference test: make tenacity's
    # exponential-jitter backoff effectively instant in tests.
    monkeypatch.setattr(
        ooc, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# --------------------------------------------------------------------------- #
# call site 1: _discover_new_docs() -- takes the AsyncClient directly, so no
# httpx.AsyncClient monkeypatching is needed here.
# --------------------------------------------------------------------------- #

class _FakeHubResp:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", ooc.HUB_URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"bad status {self.status_code}", request=request, response=response
            )


class _FlakyHubClient:
    """Raises on the first N-1 .get() calls, then serves a real terminal response."""

    def __init__(self, fail_times: int, exc=None, final_status: int = 200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.final_status = final_status
        self.calls = 0

    async def get(self, url, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeHubResp("", self.final_status)


def test_discover_new_docs_transient_timeout_is_retried_and_then_succeeds():
    client = _FlakyHubClient(fail_times=2)
    found = asyncio.run(ooc._discover_new_docs(client, set()))
    assert client.calls == 3
    assert found == []  # empty hub page -> no new docs, but the fetch itself succeeded


def test_discover_new_docs_transient_timeout_exhausted_stops_at_budget_not_hanging():
    client = _FlakyHubClient(fail_times=99)
    found = asyncio.run(ooc._discover_new_docs(client, set()))
    assert client.calls == 3  # stop_after_attempt(3), then gives up -- no infinite retry
    assert found == []  # swallowed by the function's own pre-existing catch-all


def test_discover_new_docs_real_http_error_status_is_not_retried():
    client = _FlakyHubClient(fail_times=0, final_status=404)
    found = asyncio.run(ooc._discover_new_docs(client, set()))
    assert client.calls == 1  # a real bad status is not a transport/timeout error
    assert found == []


def test_discover_new_docs_read_timeout_is_also_retried():
    client = _FlakyHubClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    found = asyncio.run(ooc._discover_new_docs(client, set()))
    assert client.calls == 2
    assert found == []


# --------------------------------------------------------------------------- #
# call site 2: OrangeburgOverageClaims.fetch()'s per-doc loop -- fetch()
# builds its OWN httpx.AsyncClient internally, so that constructor itself
# must be monkeypatched. _discover_new_docs is stubbed out so this exercises
# only the per-doc fetch; KNOWN_DOCS is shrunk to one URL so the flaky
# counter below isn't shared across three independent doc fetches.
# --------------------------------------------------------------------------- #

class _FakeDocResp:
    def __init__(self, content: bytes = b"not-a-real-document", status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", DOC_URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"bad status {self.status_code}", request=request, response=response
            )


class _FakeAsyncClient:
    """Stands in for the bare `httpx.AsyncClient` `fetch()` constructs itself."""

    def __init__(self, flaky: "_FlakyDocHttp"):
        self._flaky = flaky

    async def get(self, url, *args, **kwargs):
        return await self._flaky._get(url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FlakyDocHttp:
    def __init__(self, fail_times: int, exc=None, final_status: int = 200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.final_status = final_status
        self.calls = 0

    async def _get(self, url):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        # Bytes that match neither the xlsx nor the PDF magic header, so
        # fetch() hits its harmless "unknown_doc_type" branch and moves on --
        # keeping this test scoped to the retry wrapper, not doc parsing.
        return _FakeDocResp(b"not-a-real-document", self.final_status)

    def client_factory(self, *, timeout=30.0, follow_redirects=True, **kwargs):
        return _FakeAsyncClient(self)


async def _noop_discover(c, have):
    return []


def _patch_fetch(monkeypatch, flaky: _FlakyDocHttp):
    monkeypatch.setattr(httpx, "AsyncClient", flaky.client_factory)
    monkeypatch.setattr(ooc, "_discover_new_docs", _noop_discover)
    monkeypatch.setattr(ooc, "KNOWN_DOCS", ((DOC_URL, "2099"),))


def test_fetch_doc_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    flaky = _FlakyDocHttp(fail_times=2)
    _patch_fetch(monkeypatch, flaky)
    rows = asyncio.run(ooc.OrangeburgOverageClaims().fetch())
    assert flaky.calls == 3
    assert rows == []  # unparseable bytes -> no listings, but the fetch itself succeeded


def test_fetch_doc_transient_timeout_exhausted_stops_at_budget_not_hanging(monkeypatch):
    flaky = _FlakyDocHttp(fail_times=99)
    _patch_fetch(monkeypatch, flaky)
    rows = asyncio.run(ooc.OrangeburgOverageClaims().fetch())
    assert flaky.calls == 3  # stop_after_attempt(3), then gives up -- no infinite retry/hang
    assert rows == []  # swallowed by fetch()'s own pre-existing per-URL catch-and-continue


def test_fetch_doc_real_http_error_status_is_not_retried(monkeypatch):
    flaky = _FlakyDocHttp(fail_times=0, final_status=404)
    _patch_fetch(monkeypatch, flaky)
    rows = asyncio.run(ooc.OrangeburgOverageClaims().fetch())
    assert flaky.calls == 1  # a real bad status is not a transport/timeout error
    assert rows == []


def test_fetch_doc_read_timeout_is_also_retried(monkeypatch):
    flaky = _FlakyDocHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    _patch_fetch(monkeypatch, flaky)
    rows = asyncio.run(ooc.OrangeburgOverageClaims().fetch())
    assert flaky.calls == 2
    assert rows == []
