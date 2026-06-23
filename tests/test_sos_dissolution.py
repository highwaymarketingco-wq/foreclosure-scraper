"""SOS dissolution enrichment — circuit-breaker + status tagging.

The breaker is the reliability fix for the Cloudflare hang that ground a run for
4.5h: once SOS starts failing, the whole step must bail in a few calls.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_sos_dissolution as sos
from foreclosure_scraper.models import Listing, ListingType


def _biz(i: int) -> Listing:
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", defendant=f"Acme Holdings {i} LLC")


def test_circuit_breaker_stops_after_consecutive_failures(monkeypatch):
    monkeypatch.setattr(sos, "_SOS_BREAKER_FAILS", 5)
    calls = {"n": 0}

    async def fake_lookup(name, cache):
        calls["n"] += 1
        return None  # simulate SOS blocking every request

    monkeypatch.setattr(sos, "_lookup_nc_sos", fake_lookup)
    listings = [_biz(i) for i in range(50)]
    asyncio.run(sos.enrich_with_sos_dissolution(listings, max_check=50))
    # Breaker trips at 5 consecutive fails; with concurrency 2 a few in-flight
    # calls may land, but it must be far below the 50 targets — never grind all.
    assert calls["n"] <= 10, f"breaker did not trip: {calls['n']} calls"


def test_successful_lookup_tags_dissolved(monkeypatch):
    async def fake_lookup(name, cache):
        return {"checked": True, "status": "admin_dissolved"}

    monkeypatch.setattr(sos, "_lookup_nc_sos", fake_lookup)
    li = _biz(1)
    asyncio.run(sos.enrich_with_sos_dissolution([li], max_check=5))
    assert li.raw.get("sos_status", {}).get("status") == "admin_dissolved"


def test_active_status_not_tagged(monkeypatch):
    async def fake_lookup(name, cache):
        return {"checked": True, "status": "active"}

    monkeypatch.setattr(sos, "_lookup_nc_sos", fake_lookup)
    li = _biz(1)
    asyncio.run(sos.enrich_with_sos_dissolution([li], max_check=5))
    assert "sos_status" not in (li.raw or {})


def test_non_business_defendants_skipped(monkeypatch):
    called = {"n": 0}

    async def fake_lookup(name, cache):
        called["n"] += 1
        return None

    monkeypatch.setattr(sos, "_lookup_nc_sos", fake_lookup)
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Gaston", defendant="John Q. Smith")
    asyncio.run(sos.enrich_with_sos_dissolution([li], max_check=5))
    assert called["n"] == 0  # individual person, not an entity
