"""oconee_tax_sale.fetch: a transient transport error on the one CSV fetch gets retried,
not treated as "the whole scrape failed."

This file makes exactly one network call -- the published Google Sheet CSV that the entire
scrape depends on (no per-item loop; _parse_csv is pure local parsing). It was a bare
`c.get()` with zero retry cushioning, the same gap already fixed tonight for the Column
legal-notice API scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features(): a
single transient blip would propagate uncaught out of fetch() and zero this file's whole
output for the run, with no fallback date window to self-heal later (this source is
registered in main.DATELESS_OK_SOURCES). A real HTTP status -- including the expected
200-with-placeholder-rows state between sale cycles -- must still be handled, unretried.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import oconee_tax_sale as M

PLACEHOLDER_CSV = (
    "Item Number,Owner Name,Map Number,Description,Total Tax Due\r\n"
    ",,,The 2026 Tax Sale is scheduled for Monday, November 9 2026,\r\n"
)

REAL_ROW_CSV = (
    "Item Number,Owner Name,Map Number,Description,Total Tax Due\r\n"
    "1,John Doe,123-45-67-890,Vacant lot,\"1,234.56\"\r\n"
)


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

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, text=REAL_ROW_CSV)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = list(asyncio.run(M.OconeeTaxSale().fetch()))
    assert calls["n"] == 3
    assert len(rows) == 1
    assert rows[0].parcel_id == "123-45-67-890"


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(M.OconeeTaxSale().fetch())
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up -- not an infinite hang


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, text=PLACEHOLDER_CSV)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = list(asyncio.run(M.OconeeTaxSale().fetch()))
    assert calls["n"] == 2
    assert rows == []   # placeholder-only rows between sale cycles: correctly empty


def test_a_real_non_200_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        return MagicMock(status_code=503, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = list(asyncio.run(M.OconeeTaxSale().fetch()))
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []
