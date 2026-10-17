"""NCECourtsDivorce.fetch: a transient transport error on either httpx POST gets retried,
not treated as "zero the whole run" (the step-1 template POST) or "truncate every remaining
page" (the step-2 judgment-page POST inside the pagination loop).

Found 2026-10-17: both POSTs go through the shared ``http_client.client()`` helper, which
sets ``httpx.AsyncHTTPTransport(retries=0)`` and documents that callers must wrap their own
``AsyncRetrying`` -- neither call site here did. The step-1 POST was a bare try/except that
logged a warning and ``return []``'d on ANY exception, silently zeroing the whole run on a
single transient blip; since this source is in ``main.DATELESS_OK_SOURCES`` (no date-window
fallback), a zeroed run cannot self-heal later. The step-2 POST, inside the
``JUDGMENT_MAX_PAGES`` pagination loop, was also a bare try/except but ``break``s on any
exception -- discarding all remaining pages rather than just the one that failed. Same root
cause, same fix, as the Column legal-notice API scrapers, spartan_weekly_legals.py, and
arcgis_webmap.query_features() fixed the same night.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import http_client as _http_client_mod
from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_divorce as M

TEMPLATE_BODY = {"searchObject": {"queryString": "", "parameters": {}}}
EMPTY_PAGE_RESULT = {"searchResult": {"hits": [], "totalHits": 0}}


def _resp(payload, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload
    return r


def _fake_client(post_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.post = post_handler
        yield stub
    return _cm


def _is_template_call(content) -> bool:
    """Step-1 posts an empty body; step-2 posts the json-encoded searchObject."""
    return content == b""


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same trick the reference retry tests use: keep the real tenacity
    # wait_exponential_jitter shape but collapse the actual sleep to ~0.
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# ---- step 1: the initial empty-POST template fetch -------------------------

def test_a_transient_connect_timeout_on_the_template_post_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def post(url, content=None, **kw):
        if _is_template_call(content):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectTimeout("boom")
            return _resp(TEMPLATE_BODY)
        return _resp(EMPTY_PAGE_RESULT)

    monkeypatch.setattr(_http_client_mod, "client", _fake_client(post))
    rows = asyncio.run(M.NCECourtsDivorce().safe_run())
    assert calls["n"] == 3
    assert rows == []


def test_a_connect_timeout_on_the_template_post_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def post(url, content=None, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(_http_client_mod, "client", _fake_client(post))
    rows = asyncio.run(M.NCECourtsDivorce().safe_run())
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully (no hang)
    assert rows == []


def test_a_real_bad_status_on_the_template_post_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def post(url, content=None, **kw):
        calls["n"] += 1
        return _resp({}, status_code=503)

    monkeypatch.setattr(_http_client_mod, "client", _fake_client(post))
    rows = asyncio.run(M.NCECourtsDivorce().safe_run())
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []


# ---- step 2: the per-page judgment-search POST inside the pagination loop --

def test_a_transient_read_timeout_on_a_judgment_page_post_is_retried_and_then_succeeds(monkeypatch):
    calls = {"template": 0, "page": 0}

    async def post(url, content=None, **kw):
        if _is_template_call(content):
            calls["template"] += 1
            return _resp(TEMPLATE_BODY)
        calls["page"] += 1
        if calls["page"] < 2:
            raise httpx.ReadTimeout("slow")
        return _resp(EMPTY_PAGE_RESULT)

    monkeypatch.setattr(_http_client_mod, "client", _fake_client(post))
    rows = asyncio.run(M.NCECourtsDivorce().safe_run())
    assert calls["page"] == 2
    assert rows == []


def test_a_read_timeout_on_a_judgment_page_post_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"template": 0, "page": 0}

    async def post(url, content=None, **kw):
        if _is_template_call(content):
            calls["template"] += 1
            return _resp(TEMPLATE_BODY)
        calls["page"] += 1
        raise httpx.ReadTimeout("always slow")

    monkeypatch.setattr(_http_client_mod, "client", _fake_client(post))
    rows = asyncio.run(M.NCECourtsDivorce().safe_run())
    # stop_after_attempt(3) on page 0, then the outer except `break`s the
    # pagination loop (not an infinite hang, and page 0's own retry budget
    # doesn't bleed into additional pages).
    assert calls["page"] == 3
    assert rows == []


def test_a_malformed_page_response_is_not_retried(monkeypatch):
    """A real server-side failure on a judgment page (e.g. a non-JSON error page,
    status 200 but unparseable) is not a transport/timeout error, so it must fail
    on attempt 1 -- never silently retried as if it might clear on its own."""
    calls = {"template": 0, "page": 0}

    async def post(url, content=None, **kw):
        if _is_template_call(content):
            calls["template"] += 1
            return _resp(TEMPLATE_BODY)
        calls["page"] += 1
        bad = MagicMock()
        bad.status_code = 200
        bad.json.side_effect = ValueError("not json")
        return bad

    monkeypatch.setattr(_http_client_mod, "client", _fake_client(post))
    rows = asyncio.run(M.NCECourtsDivorce().safe_run())
    assert calls["page"] == 1   # a real parse failure is not a transport/timeout error
    assert rows == []
