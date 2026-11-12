"""charlotte_open_data.py: a transient transport error on a pagination page fetch gets
retried, not treated as "end of this run's results."

Found 2026-10-17 (gap-sweep continuation): CharlotteOpenData.fetch()'s `c.get(SERVICE_URL,
...)` inside its `while True:` pagination loop had zero retry cushioning -- the whole loop
was wrapped only in one bare `try/except Exception` that logs and breaks, never retries.
http_client.client()'s own transport sets `retries=0` and expects every caller to wrap its
own (see http_client.py's comment above `AsyncHTTPTransport(retries=0)`). Because pagination
here is sequential (each page depends on the prior loop state), a transient failure on page 1
zeroes the whole scrape's output for the run, and this scraper is registered in
main.DATELESS_OK_SOURCES (no fallback date window), so a zeroed run cannot self-heal later.
Same bug shape, same fix, already shipped for the Column legal-notice API scraper,
spartan_weekly_legals.py, and arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.city_websites import charlotte_open_data as M

_ONE_FEATURE_PAGE = {
    "features": [
        {
            "attributes": {
                "CaseNumber": "20190055069",
                "ParcelId": "06916309",
                "CaseType": "Housing",
                "FullAddress": "2601 ABELWOOD RD CHARLOTTE, NC 28216",
                "CaseStatus": "Open",
                "DateCreated": 1570744875000,
            },
            "geometry": None,
        }
    ],
    "exceededTransferLimit": False,
}


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        M, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, json=lambda: _ONE_FEATURE_PAGE)

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CharlotteOpenData().fetch())

    assert calls["n"] == 3
    assert len(out) == 1
    assert out[0].case_number == "20190055069"


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CharlotteOpenData().fetch())

    assert calls["n"] == 3   # stop_after_attempt(3), then gives up -- not an infinite retry/hang
    assert out == []


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, json=lambda: _ONE_FEATURE_PAGE)

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CharlotteOpenData().fetch())

    assert calls["n"] == 2
    assert len(out) == 1


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        return MagicMock(status_code=503, json=lambda: {})

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CharlotteOpenData().fetch())

    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert out == []


def test_a_200_with_an_error_body_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, timeout=None):
        calls["n"] += 1
        return MagicMock(status_code=200, json=lambda: {"error": {"code": 400, "message": "bad"}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CharlotteOpenData().fetch())

    assert calls["n"] == 1   # the classic HTTP-200-plus-error-body silent-death shape, unretried
    assert out == []
