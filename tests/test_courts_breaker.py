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


# ---- SC bulk county-scrape enrichment ------------------------------------------
# The per-case render + stall-breaker path was intentionally removed: SC case
# DETAIL pages are WAF-walled, so enrich now runs the search-page scraper ONCE
# per county (_scrape_county) and backfills every SC listing from that grid.
# No per-case fetch_rendered, no breaker.


async def _fake_no_sleep(*a, **k):
    return None


def test_sc_bulk_scrapes_once_per_county_not_per_case(monkeypatch):
    """40 SC cases in one county => exactly ONE county scrape (bulk), and the
    removed per-case renderer must never be touched."""
    from foreclosure_scraper.scrapers.counties_sc import sc_public_index as scpi

    calls = {"counties": [], "render": 0}

    async def fake_scrape(county):
        calls["counties"].append(county)
        # one search returns the whole grid for the county
        return [
            Listing(source="scpi", source_url="u",
                    listing_type=ListingType.FORECLOSURE_SALE,
                    state="SC", county="Spartanburg",
                    case_number=f"2026CP{i:06d}",
                    plaintiff="Acme Bank", defendant=f"Debtor {i}")
            for i in range(40)
        ]

    async def boom_render(*a, **k):
        calls["render"] += 1
        raise AssertionError("bulk SC path must not render per case")

    monkeypatch.setattr(scpi, "_scrape_county", fake_scrape)
    monkeypatch.setattr(ec, "fetch_rendered", boom_render)
    monkeypatch.setattr(ec.asyncio, "sleep", _fake_no_sleep)

    targets = [_sc(i) for i in range(40)]
    asyncio.run(ec.enrich_with_court_records(targets))

    assert calls["counties"] == ["Spartanburg"]  # bulk: one scrape, all 40 cases
    assert calls["render"] == 0                  # per-case render/breaker path gone
    assert all(li.plaintiff == "Acme Bank" for li in targets)  # empty fields backfilled
    assert targets[7].defendant == "Debtor 7"


def test_sc_bulk_does_not_overwrite_existing(monkeypatch):
    """Backfill fills EMPTY fields only — never clobbers a parsed name."""
    from foreclosure_scraper.scrapers.counties_sc import sc_public_index as scpi

    async def fake_scrape(county):
        return [Listing(source="scpi", source_url="u",
                        listing_type=ListingType.FORECLOSURE_SALE,
                        state="SC", county="Spartanburg",
                        case_number="2026CP000001",
                        plaintiff="Grid Bank", defendant="Grid Debtor")]

    monkeypatch.setattr(scpi, "_scrape_county", fake_scrape)
    monkeypatch.setattr(ec.asyncio, "sleep", _fake_no_sleep)

    li = _sc(1)
    li.plaintiff = "Original Plaintiff"
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.plaintiff == "Original Plaintiff"  # preserved, not clobbered
    assert li.defendant == "Grid Debtor"         # empty field still backfilled


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
