"""counties_sc.spartanburg_vacant: a transient transport error on a page fetch gets
retried, not treated as "end of pagination."

The investigator's confirmed bug: `fetch()`'s `while True` pagination loop over the
Spartanburg City "allvacant" ArcGIS FeatureServer wrapped `r = await c.get(LAYER,
params=params)` (plus the immediate `.json()` parse) in only a bare `try/except Exception`
that logs and immediately `break`s the loop, with zero retry. http_client.client()'s own
docstring says every caller must wrap its own AsyncRetrying; this call site never did. A
single transient blip on offset=0 permanently zeroes this dateless source's whole
~5,014-row roll for the run, and a blip on any later page silently truncates the rest --
and because this module is registered in main.DATELESS_OK_SOURCES (no fallback date
window), a zeroed/truncated run cannot self-heal later. It just silently reports an
empty/healthy result until someone notices by hand. Same root cause, same fix, as the
sibling spartanburg_condemned.py, spartan_weekly_legals.py, and
arcgis_webmap.query_features(), all fixed earlier the same night.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import spartanburg_vacant as mod


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
    # Same trick the reference test file uses: swap in a near-zero backoff so the
    # retry-exhaustion tests don't actually sleep through exponential-jitter waits.
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_on_offset_0_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _page([])  # terminal: empty page ends the loop cleanly

    monkeypatch.setattr(mod, "client", _fake_client(get))
    rows = asyncio.run(mod.SpartanburgVacant().fetch())
    assert calls["n"] == 3
    assert list(rows) == []


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(mod, "client", _fake_client(get))
    rows = asyncio.run(mod.SpartanburgVacant().fetch())
    # stop_after_attempt(3) exhausts the retry budget and reraises; the outer bare
    # except then logs a warning and breaks the pagination loop -- the run finishes
    # (with whatever it had, here nothing) instead of hanging or raising to the caller.
    assert calls["n"] == 3
    assert list(rows) == []


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return _page([])

    monkeypatch.setattr(mod, "client", _fake_client(get))
    rows = asyncio.run(mod.SpartanburgVacant().fetch())
    assert calls["n"] == 2
    assert list(rows) == []


def test_a_real_http_status_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        request = httpx.Request("GET", url)
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(mod, "client", _fake_client(get))
    rows = asyncio.run(mod.SpartanburgVacant().fetch())
    assert calls["n"] == 1   # a real bad HTTP status is not a transport/timeout error
    assert list(rows) == []


def test_a_non_transport_exception_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, params=None, **kw):
        calls["n"] += 1
        raise ValueError("not a transport/timeout error")

    monkeypatch.setattr(mod, "client", _fake_client(get))
    rows = asyncio.run(mod.SpartanburgVacant().fetch())
    assert calls["n"] == 1   # a real non-transport error fails immediately, no retry budget spent
    assert list(rows) == []


def test_pagination_still_works_once_the_retry_wrapper_is_in_place(monkeypatch):
    """Sanity check the fix didn't change request/parse behaviour: a clean two-page run
    still accumulates both pages' features (minus the government-owner row, which is
    unrelated parsing logic the retry fix must not touch)."""
    calls = {"n": 0}

    def _feature(**attrs):
        return {"attributes": attrs, "geometry": {"x": -81.93, "y": 34.92}}

    page_1 = {"features": [_feature(
        TAXPIN="711264855413", OwnerName="YARBOROUGH LOIS", TaxpayerNa=None,
        StreetAddr=None, City=None, State=None, Zip=None,
        PropertyLo="305 WIMBERLY DR", SaleDate=None, SaleAmount=None,
        YearBuilt=1965, ConditionF="FA", LivingArea=1240, BedRooms=3,
        FullBaths=1, HalfBaths=1, LandUse="SFR", PropertyTy="RES",
    )] * mod._PAGE}  # a full page -> loop asks for another page
    page_2 = {"features": [_feature(
        TAXPIN="712204145906", OwnerName="SHELL RICKY", TaxpayerNa=None,
        StreetAddr=None, City=None, State=None, Zip=None,
        PropertyLo="202 NORTH ST", SaleDate=None, SaleAmount=None,
        YearBuilt=None, ConditionF=None, LivingArea=None, BedRooms=None,
        FullBaths=None, HalfBaths=None, LandUse=None, PropertyTy=None,
    )]}  # short page -> terminal

    async def get(url, params=None, **kw):
        calls["n"] += 1
        return _page(page_1["features"]) if calls["n"] == 1 else _page(page_2["features"])

    monkeypatch.setattr(mod, "client", _fake_client(get))
    rows = list(asyncio.run(mod.SpartanburgVacant().fetch()))
    assert calls["n"] == 2
    assert len(rows) == mod._PAGE + 1
    assert {r.parcel_id for r in rows} == {"711264855413", "712204145906"}
