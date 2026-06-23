"""enrich_with_court_records stall-breaker — runs every case while healthy,
bails only on consecutive renderer failures (no time limit). The fix for the
Tyler court step that ground a full run for hours after the browser degraded.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_courts as ec
from foreclosure_scraper.models import Listing, ListingType


def _nc(i: int) -> Listing:
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", case_number=f"26-CVD-{1000 + i}")


def test_breaker_trips_on_consecutive_renderer_failures(monkeypatch):
    monkeypatch.setattr(ec, "_COURT_BREAKER_FAILS", 12)
    calls = {"n": 0}

    async def boom(url, token=None):
        calls["n"] += 1
        raise RuntimeError("render hung")

    monkeypatch.setattr(ec, "fetch_rendered", boom)
    listings = [_nc(i) for i in range(80)]
    asyncio.run(ec.enrich_with_court_records(listings))
    # Concurrency is 4, so a few extra in-flight calls land, but it must bail far
    # short of all 80 — never grind the whole list when the renderer is dead.
    assert calls["n"] <= 20, f"breaker did not trip: {calls['n']} calls"


def test_no_trip_when_healthy(monkeypatch):
    monkeypatch.setattr(ec, "_COURT_BREAKER_FAILS", 12)
    calls = {"n": 0}

    async def ok(url, token=None):
        calls["n"] += 1
        return ""  # returned render, just no match — healthy, must not trip

    monkeypatch.setattr(ec, "fetch_rendered", ok)
    monkeypatch.setattr(ec, "_apply_court_text", lambda li, content: 0)
    listings = [_nc(i) for i in range(80)]
    asyncio.run(ec.enrich_with_court_records(listings))
    assert calls["n"] == 80  # every case processed, no time limit, no trip


def test_empty_content_does_not_count_as_failure(monkeypatch):
    # Alternating empty (no-match) results must never accumulate toward the
    # breaker — only real exceptions/timeouts do.
    monkeypatch.setattr(ec, "_COURT_BREAKER_FAILS", 3)
    calls = {"n": 0}

    async def empties(url, token=None):
        calls["n"] += 1
        return None

    monkeypatch.setattr(ec, "fetch_rendered", empties)
    listings = [_nc(i) for i in range(30)]
    asyncio.run(ec.enrich_with_court_records(listings))
    assert calls["n"] == 30  # all processed despite every one being a no-match
