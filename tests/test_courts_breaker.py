"""Court-records enrichment: NC via Tyler batch search (fast/compliant), SC via
per-case render with a stall-breaker (runs every case while healthy, bails only
on consecutive renderer failures — no time limit).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_courts as ec
from foreclosure_scraper.models import Listing, ListingType


def _sc(i: int) -> Listing:
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="SC", county="Spartanburg", case_number=f"2026CP{i:06d}")


def _nc(case: str, **kw) -> Listing:
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", case_number=case, **kw)


# ---- SC per-case render breaker -------------------------------------------------

def test_sc_breaker_trips_on_consecutive_failures(monkeypatch):
    monkeypatch.setattr(ec, "_COURT_BREAKER_FAILS", 12)
    calls = {"n": 0}

    async def boom(url, token=None):
        calls["n"] += 1
        raise RuntimeError("render hung")

    monkeypatch.setattr(ec, "fetch_rendered", boom)
    asyncio.run(ec.enrich_with_court_records([_sc(i) for i in range(80)]))
    assert calls["n"] <= 20, f"breaker did not trip: {calls['n']}"


def test_sc_no_trip_when_healthy(monkeypatch):
    monkeypatch.setattr(ec, "_COURT_BREAKER_FAILS", 12)
    calls = {"n": 0}

    async def ok(url, token=None):
        calls["n"] += 1
        return ""  # returned render, no match — healthy, must process all

    monkeypatch.setattr(ec, "fetch_rendered", ok)
    monkeypatch.setattr(ec, "_apply_court_text", lambda li, content: 0)
    asyncio.run(ec.enrich_with_court_records([_sc(i) for i in range(40)]))
    assert calls["n"] == 40


# ---- NC batch-search path ------------------------------------------------------

def test_nc_batch_match_fills_empty_fields(monkeypatch):
    hit = {"caseNumber": "26 SP000359-440",
           "debtors": [{"name": "John Doe"}], "creditors": [{"name": "Acme Bank"}],
           "causeOfActionDesc": "Foreclosure", "location": "Gaston District Court"}

    async def fake_index():
        return {ec._norm_case("26 SP000359-440"): hit}

    monkeypatch.setattr(ec, "_build_nc_case_index", fake_index)
    li = _nc("26SP000359-440", raw={})
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.defendant == "John Doe" and li.plaintiff == "Acme Bank"
    assert li.raw["court_record"]["source"] == "nc_ecourts_search"


def test_nc_batch_does_not_overwrite_existing(monkeypatch):
    hit = {"caseNumber": "26 SP1-440", "debtors": [{"name": "New Debtor"}], "creditors": []}

    async def fake_index():
        return {ec._norm_case("26 SP1-440"): hit}

    monkeypatch.setattr(ec, "_build_nc_case_index", fake_index)
    li = _nc("26SP1-440", defendant="Original Defendant", raw={})
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.defendant == "Original Defendant"  # preserved


def test_no_nc_index_call_when_no_nc_listings(monkeypatch):
    called = {"n": 0}

    async def spy():
        called["n"] += 1
        return {}

    monkeypatch.setattr(ec, "_build_nc_case_index", spy)
    monkeypatch.setattr(ec, "fetch_rendered", lambda *a, **k: "")
    asyncio.run(ec.enrich_with_court_records([_sc(1)]))  # SC only
    assert called["n"] == 0  # never touches the NC search when no NC case#s
