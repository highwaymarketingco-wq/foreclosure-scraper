"""fema_disasters.FEMADisasters.fetch: a transient transport error on the single
OpenFEMA API call gets retried, not treated as "the whole scrape failed."

Found 2026-10-17 (gap-sweep): this is the file's ONLY network call (a single GET to
the OpenFEMA API inside FEMADisasters.fetch(), via the shared http_client.client()
context manager) and the whole scrape's output depends on it. client() itself
deliberately does NOT retry (http_client.py builds its transport with
httpx.AsyncHTTPTransport(retries=0); its own comment says callers already wrap their
own AsyncRetrying), and the bare c.get() here used none -- the surrounding
try/except Exception only logs and returns an empty list on any failure, including
httpx.TransportError/TimeoutException. A single transient blip used to permanently
zero this dateless source's whole run (national.fema_disasters has no fallback date
window), reported as a healthy empty result. Same root cause, same fix, as the
Column legal-notice API scraper, spartan_weekly_legals.py, and arcgis_webmap's
query_features() fixed earlier the same gap-sweep.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import fema_disasters as M

_REAL_ROW = {
    "femaDeclarationString": "FM-5582-NC",
    "disasterNumber": 5582,
    "state": "NC",
    "declarationType": "FM",
    "declarationDate": "2025-05-03T00:00:00.000Z",
    "incidentType": "Fire",
    "declarationTitle": "SUNSET DRIVE FIRE",
    "ihProgramDeclared": False,
    "iaProgramDeclared": False,
    "designatedArea": "Brunswick (County)",
}
_GOOD_PAYLOAD = {"DisasterDeclarationsSummaries": [_REAL_ROW]}


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter", lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, json=lambda: _GOOD_PAYLOAD)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.FEMADisasters().safe_run())
    assert calls["n"] == 3
    assert len(rows) == 1
    assert rows[0].county == "Brunswick"


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_crashes(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    # asyncio.wait_for guards against a true hang -- if the fix regressed to an
    # unbounded retry loop, this would time out instead of completing.
    rows = asyncio.run(asyncio.wait_for(M.FEMADisasters().safe_run(), timeout=5))
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully
    assert rows == []


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, json=lambda: _GOOD_PAYLOAD)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.FEMADisasters().safe_run())
    assert calls["n"] == 2
    assert len(rows) == 1


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        return MagicMock(status_code=503, json=lambda: {})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.FEMADisasters().safe_run())
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []
