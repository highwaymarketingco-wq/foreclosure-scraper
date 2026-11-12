"""national.hubzu: a transient transport error on a network call gets retried, not
treated as "this state has no listings" / "this listing has no gallery."

Found 2026-10-17 (gap-sweep, http_client.client() unprotected-caller audit):
Hubzu.fetch() makes 2 real external calls per run, both via the shared
http_client.client() helper -- which does NOT retry internally (its transport is
built with retries=0, and its own comment says callers already wrap their own
AsyncRetrying). hubzu.py called `c.get(...)` raw on both sites with zero retry
cushioning, same root cause already fixed tonight for the Column legal-notice API
scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features().

Primary site (the list-page call, once per state in `for i, st in
enumerate(states):`, states=("NC","SC")): only a bare try/except Exception ->
log + continue. A single transient blip here permanently zeroed that whole
state's listing set for the run (up to ~50% of this source's output), and
hubzu.py is in main.DATELESS_OK_SOURCES -- no fallback date window to self-heal,
so it just silently under-reported until someone noticed by hand.

Secondary site (the per-listing gallery-detail call): same bare try/except, but
a true per-item loop where the base listing row is already appended to
self.partial/out BEFORE this call runs -- so a failure here only drops that one
listing's extra gallery photos, not the listing itself. Fixed for the same
consistency/robustness reason, lower severity.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import hubzu as M

# A minimal but real-shaped search-tuple item: just enough for _parse_item to
# accept it (street + listingUrl) and for _property_id to find a gallery pid.
_ITEM = {
    "propertyCategory": "REO",
    "propAddress": {
        "streetNumber": "100",
        "streetName": "Main St",
        "state": "NC",
        "county": "Wake",
        "city": "Raleigh",
        "zip": "27601",
    },
    "listingUrl": "/nc/raleigh/auction-123456",
    "listingId": "123456AUCN1",
}


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


def _resp(status_code=200, payload=None):
    return MagicMock(status_code=status_code, json=lambda: (payload or {}))


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        M, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# ---------------------------------------------------------------------------
# Primary site: the per-state list-page call (API.format(state=st))
# ---------------------------------------------------------------------------

def test_list_call_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"NC": 0, "SC": 0}

    async def get(url, **kw):
        if "state=NC" in url:
            calls["NC"] += 1
            if calls["NC"] < 3:
                raise httpx.ConnectTimeout("boom")
            return _resp(200, {"data": {"srpTupples": []}})
        calls["SC"] += 1
        return _resp(200, {"data": {"srpTupples": []}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["NC"] == 3   # 2 failures + 1 success, within stop_after_attempt(3)
    assert calls["SC"] == 1   # unaffected -- its own first try succeeds
    assert rows == []


def test_list_call_connect_timeout_that_never_clears_still_gives_up_not_hangs(monkeypatch):
    calls = {"NC": 0, "SC": 0}

    async def get(url, **kw):
        if "state=NC" in url:
            calls["NC"] += 1
            raise httpx.ConnectTimeout("always boom")
        calls["SC"] += 1
        return _resp(200, {"data": {"srpTupples": []}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["NC"] == 3   # stop_after_attempt(3), then gives up -- caught + continue, no hang
    assert calls["SC"] == 1   # the other state still gets its own turn, not aborted
    assert rows == []


def test_list_call_read_timeout_is_also_retried(monkeypatch):
    calls = {"NC": 0, "SC": 0}

    async def get(url, **kw):
        if "state=NC" in url:
            calls["NC"] += 1
            if calls["NC"] < 2:
                raise httpx.ReadTimeout("slow")
            return _resp(200, {"data": {"srpTupples": []}})
        calls["SC"] += 1
        return _resp(200, {"data": {"srpTupples": []}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["NC"] == 2
    assert rows == []


def test_list_call_real_bad_status_is_not_retried(monkeypatch):
    # A bad HTTP status is returned as an ordinary response (no exception raised),
    # so it never enters the retry loop's exception path at all -- exactly one call.
    calls = {"NC": 0, "SC": 0}

    async def get(url, **kw):
        if "state=NC" in url:
            calls["NC"] += 1
            return _resp(503, {})
        calls["SC"] += 1
        return _resp(200, {"data": {"srpTupples": []}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["NC"] == 1   # a real bad status is not a transport/timeout error
    assert calls["SC"] == 1
    assert rows == []


# ---------------------------------------------------------------------------
# Secondary site: the per-listing gallery-detail call (DETAIL_API)
# ---------------------------------------------------------------------------

def test_detail_call_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"NC_list": 0, "SC_list": 0, "detail": 0}

    async def get(url, **kw):
        if "portal/auctions" in url:
            if "state=NC" in url:
                calls["NC_list"] += 1
                return _resp(200, {"data": {"srpTupples": [_ITEM]}})
            calls["SC_list"] += 1
            return _resp(200, {"data": {"srpTupples": []}})
        assert "getNewPdpDetails" in url
        calls["detail"] += 1
        if calls["detail"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _resp(200, {"propertyDetails": {"imageDetails": [
            {"imageStoragePath": "//image-prod.hubzu.com/a.jpg"},
        ]}})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["detail"] == 3
    assert len(rows) == 1
    assert rows[0].raw["images"]["real"] == ["https://image-prod.hubzu.com/a.jpg"]


def test_detail_call_connect_timeout_that_never_clears_still_ships_base_listing(monkeypatch):
    calls = {"NC_list": 0, "SC_list": 0, "detail": 0}

    async def get(url, **kw):
        if "portal/auctions" in url:
            if "state=NC" in url:
                calls["NC_list"] += 1
                return _resp(200, {"data": {"srpTupples": [_ITEM]}})
            calls["SC_list"] += 1
            return _resp(200, {"data": {"srpTupples": []}})
        assert "getNewPdpDetails" in url
        calls["detail"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["detail"] == 3   # stop_after_attempt(3), then gives up -- caught + continue
    # The base listing row was already appended before the gallery call ran --
    # a fully exhausted gallery retry only drops the EXTRA photos, not the row.
    assert len(rows) == 1
    assert "images" not in rows[0].raw or rows[0].raw.get("images", {}).get("real") in (None, [])


def test_detail_call_real_bad_status_is_not_retried(monkeypatch):
    calls = {"NC_list": 0, "SC_list": 0, "detail": 0}

    async def get(url, **kw):
        if "portal/auctions" in url:
            if "state=NC" in url:
                calls["NC_list"] += 1
                return _resp(200, {"data": {"srpTupples": [_ITEM]}})
            calls["SC_list"] += 1
            return _resp(200, {"data": {"srpTupples": []}})
        assert "getNewPdpDetails" in url
        calls["detail"] += 1
        return _resp(503, {})

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.Hubzu().safe_run())
    assert calls["detail"] == 1   # a real bad status is not a transport/timeout error
    assert len(rows) == 1
