"""polk_tax.PolkTaxAuction._fetch_auction: a transient transport error on the
Kania Law Firm auction-page fetch gets retried, not treated as "the whole run
failed."

Found 2026-11-07 (gap-sweep): this file makes exactly ONE unprotected network
call -- `r = await c.get(URL, headers=HEADERS)` inside
`async with client(timeout=20.0) as c:` in `_fetch_auction` -- and it had zero
retry cushioning, the same root-cause shape already fixed this same week for
the Column legal-notice API scraper, spartan_weekly_legals.py,
arcgis_webmap.query_features(), and cleveland_tax.py. http_client's own
client() docstring says every caller must wrap its own retries; this one
never did. `fetch()` calls `_fetch_auction()` FIRST and only banks
self.partial AFTER it returns, so a single connection reset/timeout here
propagated uncaught out of fetch() entirely -- zeroing BOTH the auction rows
AND the much larger delinquent-tax-search path that runs after it in the same
call. Since this scraper is registered in main.DATELESS_OK_SOURCES (no
fallback date window), a zeroed run can't self-heal later; it just silently
reports an empty/healthy result forever.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import polk_tax as M

PAGE = (
    "<html><body>"
    "Upcoming Auction Date: March 10th, 2026 "
    "Location: Polk County Courthouse, 1 Courthouse St, Columbus NC "
    "P65-38&nbsp;&nbsp;$25,000.00"
    "</body></html>"
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
        return MagicMock(status_code=200, text=PAGE)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.PolkTaxAuction()._fetch_auction())
    assert calls["n"] == 3
    rows = list(rows)
    assert len(rows) == 1
    assert rows[0].parcel_id == "P65-38"


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(M.PolkTaxAuction()._fetch_auction())
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, text=PAGE)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.PolkTaxAuction()._fetch_auction())
    assert calls["n"] == 2
    assert len(list(rows)) == 1


def test_a_real_bad_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        return MagicMock(status_code=503, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.PolkTaxAuction()._fetch_auction())
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []
