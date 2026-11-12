"""national.hud_homestore._fetch_state: a transient transport error on either the anti-CSRF
token fetch or the search-handler POST gets retried, not treated as "zero this state."

Found 2026-10-17 (gap-sweep): both Step 1 (`GET /searchresult?stateCode=`, which harvests the
anti-CSRF cookie + token) and Step 2 (`POST /searchresult?handler=GetFilteredResult`, the actual
search handler that returns the state's full listing set) were wrapped in only a bare
`try/except Exception: log.warning(...); return []`, with zero retry. http_client.client()'s own
docstring says every caller must wrap its own AsyncRetrying (its transport is built with
`retries=0`); this module opens `client()` directly and never did. A single transient blip on
either call permanently zeroed that state's whole listing output for the run, and because
national.hud_homestore is registered in main.DATELESS_OK_SOURCES (no fallback date window), a
zeroed run can't self-heal later -- it just silently reports an empty/healthy result. The
per-listing broker-contact fetch in the Step 3 loop had the same bare-call shape (lower severity:
a failure there only `continue`s past one listing's enrichment, since the search rows already
shipped) and got the same fix. Same root cause, same fix, as the Column legal-notice API
scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features(), all fixed earlier this
same audit.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import hud_homestore as M

# A minimal page carrying the anti-CSRF token TOKEN_RE looks for.
_VALID_INITIAL_HTML = (
    '<input id="request-verification-token" name="x" type="hidden" '
    'value="TESTTOKEN123" />'
)

_EMPTY_SEARCH_JSON = {"searchresult": []}

_ONE_ROW_SEARCH_JSON = {
    "searchresult": [
        {"propertyAddress": "123 Testa Placeholder St", "propertyCaseNumber": "387-000001",
         "propertyState": "NC"},
    ]
}


def _resp(status_code=200, text="", json_data=None):
    r = MagicMock(status_code=status_code, text=text)
    if json_data is not None:
        r.json = MagicMock(return_value=json_data)
    return r


def _fake_client(get_handler, post_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        stub.post = post_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        M, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# --- Step 1 (GET /searchresult?stateCode=): the anti-CSRF token fetch ------------------------

def test_step1_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    get_calls = {"n": 0}
    post_calls = {"n": 0}

    async def get(url, **kw):
        assert "/searchresult?stateCode=" in url
        get_calls["n"] += 1
        if get_calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _resp(200, text=_VALID_INITIAL_HTML)

    async def post(url, **kw):
        post_calls["n"] += 1
        return _resp(200, json_data=_EMPTY_SEARCH_JSON)

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert get_calls["n"] == 3
    assert post_calls["n"] == 1   # step 2 was reached, proving step 1 actually recovered
    assert rows == []


def test_step1_timeout_that_never_clears_returns_empty_not_hangs(monkeypatch):
    get_calls = {"n": 0}

    async def get(url, **kw):
        get_calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    async def post(url, **kw):
        raise AssertionError("step 2 must not run when step 1 never recovers")

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert get_calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully
    assert rows == []


def test_step1_real_bad_status_is_not_retried(monkeypatch):
    get_calls = {"n": 0}

    async def get(url, **kw):
        get_calls["n"] += 1
        return _resp(500, text="")

    async def post(url, **kw):
        raise AssertionError("step 2 must not run when step 1 returns a real bad status")

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert get_calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []


# --- Step 2 (POST .../handler=GetFilteredResult): the actual search handler ------------------

def test_step2_read_timeout_is_retried_and_then_succeeds(monkeypatch):
    post_calls = {"n": 0}

    async def get(url, **kw):
        return _resp(200, text=_VALID_INITIAL_HTML)

    async def post(url, **kw):
        post_calls["n"] += 1
        if post_calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return _resp(200, json_data=_EMPTY_SEARCH_JSON)

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert post_calls["n"] == 2
    assert rows == []


def test_step2_timeout_that_never_clears_returns_empty_not_hangs(monkeypatch):
    post_calls = {"n": 0}

    async def get(url, **kw):
        return _resp(200, text=_VALID_INITIAL_HTML)

    async def post(url, **kw):
        post_calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert post_calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully
    assert rows == []


def test_step2_real_bad_status_is_not_retried(monkeypatch):
    post_calls = {"n": 0}

    async def get(url, **kw):
        return _resp(200, text=_VALID_INITIAL_HTML)

    async def post(url, **kw):
        post_calls["n"] += 1
        return _resp(503, text="")

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert post_calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []


# --- Step 3 (per-listing GET /propertydetails?caseNumber=): the broker-contact fetch ---------

def test_step3_broker_fetch_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    broker_calls = {"n": 0}

    async def get(url, **kw):
        if "/searchresult?stateCode=" in url:
            return _resp(200, text=_VALID_INITIAL_HTML)
        assert "/propertydetails?caseNumber=" in url
        broker_calls["n"] += 1
        if broker_calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _resp(200, text="<html><body>no broker card here</body></html>")

    async def post(url, **kw):
        return _resp(200, json_data=_ONE_ROW_SEARCH_JSON)

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert broker_calls["n"] == 3
    assert len(rows) == 1   # the search row shipped regardless of the broker page's fate


def test_step3_broker_fetch_timeout_that_never_clears_skips_just_that_listing(monkeypatch):
    broker_calls = {"n": 0}

    async def get(url, **kw):
        if "/searchresult?stateCode=" in url:
            return _resp(200, text=_VALID_INITIAL_HTML)
        broker_calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    async def post(url, **kw):
        return _resp(200, json_data=_ONE_ROW_SEARCH_JSON)

    monkeypatch.setattr(M, "client", _fake_client(get, post))
    rows = asyncio.run(M._fetch_state("NC"))
    assert broker_calls["n"] == 3   # stop_after_attempt(3), then continues past this listing
    assert len(rows) == 1
    assert "listing_broker" not in rows[0].raw.get("hud_homestore", {})
