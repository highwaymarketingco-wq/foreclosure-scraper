"""Regression tests for two 2026-09-14 fixes in enrichment_owner_mailing.py:

1. _query_page must detect an ArcGIS error body (HTTP 200 + {"error": ...}) and
   trip the shared host breaker, instead of silently returning [] — which is
   indistinguishable from a genuine zero-match query. SCDOT has been token-
   walled since 2026-08-12 (see tests/test_scdot_breaker.py); this module was
   never patched to notice, so every SC lead with no dedicated COUNTY_GIS layer
   spent a full request against a dead endpoint on every run, unlogged.

2. _resolve_one must supplement mailing from SCDOT when a county's own
   dedicated layer resolves owner+situs but has no mailing field at all
   (Charleston, Beaufort: verified live, their public layers carry no mailing
   column). Before the fix, `res is None` gated the whole SCDOT fallback block,
   so a dedicated layer that resolved ANYTHING — even with zero chance of ever
   producing a mailing address — permanently blocked the one source that could.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper import enrichment_arcgis as A
from foreclosure_scraper import enrichment_owner_mailing as M
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


@pytest.fixture(autouse=True)
def _reset_breaker():
    A._WALLED_HOSTS.clear(); A._HOST_FAILS.clear()
    yield
    A._WALLED_HOSTS.clear(); A._HOST_FAILS.clear()


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self._b = body

    def json(self):
        return self._b


class _Client:
    """Fake httpx.AsyncClient.get keyed by URL prefix -> canned JSON body."""
    def __init__(self, routes: dict[str, dict]):
        self._routes = routes

    async def get(self, url, params=None, timeout=None):
        for prefix, body in self._routes.items():
            if url.startswith(prefix):
                return _Resp(body)
        return _Resp({"features": []})


def _feature(attrs: dict) -> dict:
    return {"features": [{"attributes": attrs}]}


def test_query_page_trips_breaker_on_token_error_instead_of_returning_empty():
    client = _Client({A.SCDOT_BASE: {"error": {"code": 499, "message": "Token Required"}}})

    async def _run():
        return await M._query_page(client, f"{A.SCDOT_BASE}/10", "1=1")

    rows, more = asyncio.run(_run())
    assert rows == []
    assert more is False
    assert A.scdot_walled() is True


def test_query_page_does_not_trip_breaker_on_a_genuine_zero_match():
    client = _Client({A.SCDOT_BASE: {"features": []}})

    async def _run():
        return await M._query_page(client, f"{A.SCDOT_BASE}/10", "PID='nope'")

    rows, more = asyncio.run(_run())
    assert rows == []
    assert A.scdot_walled() is False


def test_dedicated_layer_with_no_mail_field_is_supplemented_by_scdot():
    charleston_url = M.COUNTY_GIS["SC:Charleston"]["url"]
    scdot_layer_url = f"{A.SCDOT_BASE}/10"  # Charleston = layer 10

    client = _Client({
        charleston_url: _feature({"OWNER": "LEE REBECCA SUE", "ADDR": "5030 TIMBER RACE CRSE",
                                   "PID": "2480400055"}),
        scdot_layer_url: _feature({"OWNER": "LEE REBECCA SUE", "OWNER_ADDR": "PO BOX 123",
                                    "CITY": "CHARLESTON  SC", "ZIPCODE": "29403",
                                    "PHYS_ADDR": "5030 TIMBER RACE CRSE", "TMS": "2480400055"}),
    })
    li = Listing(source="t", source_url="https://x", state="SC", county="Charleston",
                 parcel_id="2480400055", street_address="5030 TIMBER RACE CRSE",
                 property_kind=PropertyKind.SINGLE_FAMILY,
                 listing_type=ListingType.FORECLOSURE_SALE)

    res = asyncio.run(M._resolve_one(client, li))
    assert res is not None
    assert res["owner"] == "LEE REBECCA SUE"
    # from the dedicated layer, never overwritten
    assert res["situs"] == "5030 TIMBER RACE CRSE"
    # from the SCDOT supplement — this is the fix under test
    assert res["mailing"]
    assert "PO BOX 123" in res["mailing"]
    assert res.get("mailing_source") == "scdot_sc"


def test_dedicated_layer_supplement_is_skipped_once_scdot_is_walled():
    """If SCDOT is already known-dead, the supplement attempt must not fire —
    matches the existing breaker contract (no wasted requests once tripped)."""
    A.mark_scdot_walled()
    charleston_url = M.COUNTY_GIS["SC:Charleston"]["url"]
    client = _Client({
        charleston_url: _feature({"OWNER": "LEE REBECCA SUE", "ADDR": "5030 TIMBER RACE CRSE",
                                   "PID": "2480400055"}),
    })
    li = Listing(source="t", source_url="https://x", state="SC", county="Charleston",
                 parcel_id="2480400055", street_address="5030 TIMBER RACE CRSE",
                 property_kind=PropertyKind.SINGLE_FAMILY,
                 listing_type=ListingType.FORECLOSURE_SALE)

    res = asyncio.run(M._resolve_one(client, li))
    assert res is not None
    assert res["owner"] == "LEE REBECCA SUE"
    assert not res.get("mailing")
    assert "mailing_source" not in res
