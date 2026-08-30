"""SCDOT token-wall circuit-breaker.

SC_Parcels went token-walled 2026-08-12 (HTTP 200 + {"error":{"code":499,
"message":"Token Required"}}). Five enrichers query SCDOT per SC lead; re-hitting
the dead endpoint for every SC lead dragged a full run to 16h on 2026-08-13. The
breaker trips on the first token-required response and short-circuits every later
SCDOT call. SCDOT stays wired (source kept) — a fresh process resolves normally if
a token is ever provided. This guards the skip so the marathon can't come back.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper import enrichment_arcgis as A
from foreclosure_scraper import enrichment_parcel_from_geo as G
from foreclosure_scraper import enrichment_footprint_sqft as F
from foreclosure_scraper.models import Listing, PropertyKind, ListingType


@pytest.fixture(autouse=True)
def _reset_breaker():
    A._WALLED_HOSTS.clear(); A._HOST_FAILS.clear()
    yield
    A._WALLED_HOSTS.clear(); A._HOST_FAILS.clear()


def test_generic_host_breaker_and_consecutive_failures():
    # a NON-scdot host trips independently, and only after N consecutive hard fails
    nc = "https://services.nconemap.gov/secure/rest/services/x/FeatureServer/0/query"
    assert not A.host_walled(nc)
    for _ in range(A._HOST_FAIL_TRIP - 1):
        A.note_host_hard_failure(nc)
    assert not A.host_walled(nc)          # not yet
    A.note_host_hard_failure(nc)
    assert A.host_walled(nc)              # tripped at the threshold
    assert not A.scdot_walled()           # a different host is unaffected
    # a clean response resets the counter for a host that hasn't tripped
    other = "https://gis.buncombecounty.org/x/query"
    A.note_host_hard_failure(other); A.note_host_ok(other)
    assert A._HOST_FAILS[A._host_of(other)] == 0


def test_token_error_detection():
    assert A.is_scdot_token_error({"error": {"code": 499, "message": "Token Required"}})
    assert A.is_scdot_token_error({"error": {"message": "token required"}})
    assert not A.is_scdot_token_error({"features": []})
    assert not A.is_scdot_token_error({"error": {"code": 400, "message": "bad where"}})
    assert not A.is_scdot_token_error(None)


def test_mark_is_idempotent_and_stateful():
    assert A.scdot_walled() is False
    A.mark_scdot_walled()
    assert A.scdot_walled() is True
    A.mark_scdot_walled()  # no raise, stays tripped
    assert A.scdot_walled() is True


def test_parcel_from_geo_short_circuits_when_walled():
    """When the breaker is tripped, the SC point lane returns '' without any HTTP."""
    A.mark_scdot_walled()
    li = Listing(source="t", source_url="https://x", state="SC", county="Spartanburg",
                 latitude=34.949, longitude=-81.932,
                 property_kind=PropertyKind.SINGLE_FAMILY,
                 listing_type=ListingType.FORECLOSURE_SALE)

    async def _run():
        # No client needed: it must bail before touching the network. Pass None to
        # prove no HTTP call happens (a network call would AttributeError on None).
        return await G._parcel_from_point_sc(None, li)

    assert asyncio.run(_run()) == ""


def test_footprint_ring_short_circuits_when_walled():
    A.mark_scdot_walled()
    assert F._scdot_parcel_ring("SC", "Spartanburg", "12345") is None


def test_arc_query_trips_breaker_on_scdot_token_error():
    """A token-required response from an SCDOT url trips the breaker; a non-SCDOT
    error (e.g. NC OneMap) does NOT."""
    class _Resp:
        status_code = 200
        def __init__(self, body): self._b = body
        def json(self): return self._b

    class _Client:
        def __init__(self, body): self._b = body
        async def get(self, *a, **k): return _Resp(self._b)

    tok = {"error": {"code": 499, "message": "Token Required"}}

    async def _scdot():
        return await G._arc_query(_Client(tok),
                                  f"{A.SCDOT_BASE}/42/query", {"f": "json"})
    assert asyncio.run(_scdot()) is None
    assert A.scdot_walled() is True

    # reset + a token error from a NON-scdot host must NOT trip the SCDOT breaker
    # (it trips the NC host instead, leaving SCDOT clear)
    A._WALLED_HOSTS.clear(); A._HOST_FAILS.clear()

    async def _nc():
        return await G._arc_query(_Client(tok),
                                  "https://services.nconemap.gov/x/query", {"f": "json"})
    assert asyncio.run(_nc()) is None
    assert A.scdot_walled() is False
