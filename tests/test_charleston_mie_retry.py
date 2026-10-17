"""charleston_mie.CharlestonMasterInEquity.fetch(): the two unprotected network calls
(the MASTER'S AUCTION LIST GET and the UncontestedRoster.pdf HEARING-roster GET) get
retried on a transient transport/timeout error instead of silently zeroing that source
for the whole run.

Found 2026-10-16 (gap-sweep): fetch() opens http_client.client() directly and calls
c.get() itself for both URLs -- the auction list (primary, richest source) and the
hearing roster (earliest-signal secondary source). Each sits inside a bare
try/except Exception that only logs and moves on -- no AsyncRetrying, no manual
backoff loop, no @retry decorator anywhere in this file, even though
http_client.client() itself adds zero implicit retry (its own docstring says callers
must wrap their own AsyncRetrying). Each GET is a single request the whole
corresponding method's output depends on, so a transient connection reset/timeout
permanently zeroed that slice of the scrape for the run -- and because this source is
registered in main.DATELESS_OK_SOURCES with no fallback date window, a zeroed run never
self-heals later. Same root cause, same fix, as the Column legal-notice API scrapers,
spartan_weekly_legals.py, and arcgis_webmap.query_features(), all fixed the same night.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
import structlog
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import charleston_mie as cmie_module
from foreclosure_scraper.scrapers.counties_sc.charleston_mie import CharlestonMasterInEquity


def _fake_client_factory(get_impl):
    """Build a `client`-shaped async context-manager factory, mirroring the
    established pattern in tests/test_charleston_mie.py."""
    class _FakeHTTPClient:
        async def get(self, url, **kw):
            return await get_impl(url, **kw)

    class _CM:
        async def __aenter__(self):
            return _FakeHTTPClient()

        async def __aexit__(self, *a):
            return False

    def _factory(**kw):
        return _CM()

    return _factory


class _FakeResp:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        cmie_module, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# ---------------------------------------------------------------------------
# (1) Auction list — primary call site.
# ---------------------------------------------------------------------------

def test_auction_list_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def _get(url, **kw):
        if url == cmie_module.AUCTION_LIST_URL:
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectTimeout("boom")
            return _FakeResp(200, b"<html>auction ok</html>")
        return _FakeResp(200, b"%PDF-fake")

    monkeypatch.setattr(cmie_module, "parse_auction_list", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "parse_hearing_roster", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "client", _fake_client_factory(_get))

    with structlog.testing.capture_logs() as logs:
        out = asyncio.run(CharlestonMasterInEquity().fetch())

    assert calls["n"] == 3
    assert out == []
    assert "charleston_mie.auction_list_failed" not in str(logs)


def test_auction_list_timeout_that_never_clears_gives_up_after_budget_not_hang(monkeypatch):
    calls = {"n": 0}

    async def _get(url, **kw):
        if url == cmie_module.AUCTION_LIST_URL:
            calls["n"] += 1
            raise httpx.ConnectTimeout("always boom")
        return _FakeResp(200, b"%PDF-fake")

    monkeypatch.setattr(cmie_module, "parse_hearing_roster", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "client", _fake_client_factory(_get))

    with structlog.testing.capture_logs() as logs:
        out = asyncio.run(CharlestonMasterInEquity().fetch())

    assert calls["n"] == 3  # stop_after_attempt(3), then gives up -- not an infinite hang
    assert out == []
    assert "charleston_mie.auction_list_failed" in str(logs)


def test_auction_list_real_bad_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def _get(url, **kw):
        if url == cmie_module.AUCTION_LIST_URL:
            calls["n"] += 1
            return _FakeResp(500, b"")
        return _FakeResp(200, b"%PDF-fake")

    monkeypatch.setattr(cmie_module, "parse_hearing_roster", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "client", _fake_client_factory(_get))

    out = asyncio.run(CharlestonMasterInEquity().fetch())

    assert calls["n"] == 1  # a real bad HTTP status is not a transport/timeout error
    assert out == []


# ---------------------------------------------------------------------------
# (2) Hearing roster — secondary call site.
# ---------------------------------------------------------------------------

def test_hearing_roster_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def _get(url, **kw):
        if url == cmie_module.AUCTION_LIST_URL:
            return _FakeResp(200, b"<html>auction</html>")
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ReadTimeout("slow")
        return _FakeResp(200, b"%PDF-fake")

    monkeypatch.setattr(cmie_module, "parse_auction_list", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "parse_hearing_roster", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "client", _fake_client_factory(_get))

    with structlog.testing.capture_logs() as logs:
        out = asyncio.run(CharlestonMasterInEquity().fetch())

    assert calls["n"] == 3
    assert out == []
    assert "charleston_mie.hearing_roster_failed" not in str(logs)


def test_hearing_roster_timeout_that_never_clears_gives_up_after_budget_not_hang(monkeypatch):
    calls = {"n": 0}

    async def _get(url, **kw):
        if url == cmie_module.AUCTION_LIST_URL:
            return _FakeResp(200, b"<html>auction</html>")
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(cmie_module, "parse_auction_list", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "client", _fake_client_factory(_get))

    with structlog.testing.capture_logs() as logs:
        out = asyncio.run(CharlestonMasterInEquity().fetch())

    assert calls["n"] == 3  # stop_after_attempt(3), then gives up -- not an infinite hang
    assert out == []
    assert "charleston_mie.hearing_roster_failed" in str(logs)


def test_hearing_roster_real_bad_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def _get(url, **kw):
        if url == cmie_module.AUCTION_LIST_URL:
            return _FakeResp(200, b"<html>auction</html>")
        calls["n"] += 1
        return _FakeResp(404, b"")

    monkeypatch.setattr(cmie_module, "parse_auction_list", lambda data, url: [])
    monkeypatch.setattr(cmie_module, "client", _fake_client_factory(_get))

    out = asyncio.run(CharlestonMasterInEquity().fetch())

    assert calls["n"] == 1  # a real bad HTTP status is not a transport/timeout error
    assert out == []
