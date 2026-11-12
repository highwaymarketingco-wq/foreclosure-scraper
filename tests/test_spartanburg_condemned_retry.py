"""spartanburg_condemned: a transient transport error on a page fetch gets retried, not
treated as "end of pagination."

The investigator's confirmed bug: `fetch()`'s `while True` pagination loop over the
Spartanburg County CAMA_Parcels ArcGIS FeatureServer wrapped `r = await c.get(LAYER,
params=params)` in only a bare `try/except Exception` that logs and immediately `break`s
with zero retry. Same root cause, same fix, as the Column legal-notice API scrapers,
spartan_weekly_legals.py, and arcgis_webmap.query_features(), fixed earlier the same
night: http_client.client()'s own docstring says every caller wraps its own AsyncRetrying;
this call site never did. A single transient blip on offset=0 permanently zeroes the whole
scrape's output for this run, and because this module is registered in
main.DATELESS_OK_SOURCES (no fallback date window), a zeroed run cannot self-heal later --
it just silently reports an empty/healthy result until someone notices by hand.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import spartanburg_condemned as M


def _page(features):
    return MagicMock(json=lambda: {"features": features})


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


def test_a_transient_connect_timeout_on_offset_0_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _page([])  # terminal: empty page ends the loop cleanly

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanburgCondemned().fetch())
    assert calls["n"] == 3
    assert list(rows) == []


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanburgCondemned().fetch())
    assert calls["n"] == 3   # stop_after_attempt(3), then the outer bare except logs + breaks
    assert list(rows) == []


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return _page([])

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanburgCondemned().fetch())
    assert calls["n"] == 2
    assert list(rows) == []


def test_a_real_http_error_body_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        return MagicMock(json=lambda: {"error": {"code": 400, "message": "layer unavailable"}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanburgCondemned().fetch())
    assert calls["n"] == 1   # the classic HTTP-200-plus-error-body shape is not a transport error
    assert list(rows) == []


def test_a_non_transport_exception_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        raise ValueError("not a transport/timeout error")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanburgCondemned().fetch())
    assert calls["n"] == 1   # a real non-transport error fails immediately, no retry budget spent
    assert list(rows) == []
