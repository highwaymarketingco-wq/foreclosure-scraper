"""terry_howe_flc.TerryHoweFLC.fetch: a transient transport error on the single catalog fetch
gets retried, not treated as "end of this run's results."

2026-10-17 (gap-sweep): this file makes exactly one network call -- GET
/wp-json/wp/v2/auctions?per_page=100, the whole FLC catalog in one response. The bare
`try: r = await c.get(...) except Exception: return []` around it was a catch-and-give-up with
zero re-attempts: a single httpx.TransportError/TimeoutException permanently zeroed the whole
scrape's result for that run. Same root cause, same fix, as the Column legal-notice API
scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features fixed earlier the same
night -- http_client.client()'s own docstring says every caller is expected to wrap its own
AsyncRetrying.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import terry_howe_flc as M

EMPTY_CATALOG: list = []


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, json=lambda: EMPTY_CATALOG)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.TerryHoweFLC().safe_run())
    assert calls["n"] == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.TerryHoweFLC().safe_run())
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully (no hang)
    assert rows == []


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, json=lambda: EMPTY_CATALOG)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.TerryHoweFLC().safe_run())
    assert calls["n"] == 2
    assert rows == []


def test_a_real_bad_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        return MagicMock(status_code=503, json=lambda: EMPTY_CATALOG)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.TerryHoweFLC().safe_run())
    assert calls["n"] == 1   # a real bad HTTP status is not a transport/timeout error
    assert rows == []
