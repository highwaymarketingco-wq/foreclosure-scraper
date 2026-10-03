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


def test_successful_lookup_also_tags_sos_dissolution(monkeypatch):
    """Regression for the 2026-10-02 key-mismatch found investigating why the
    sos_dissolution board column sat at 0/148 counties: this enrichment only
    ever wrote `sos_status`, while web_artifact.py's RAW_KEEP and every
    downstream coverage counter (comprehensive_audit.py, merge_title_search.py)
    read `sos_dissolution` instead -- so a real hit was invisible to every
    count. Both keys must carry the same info dict now."""
    async def fake_lookup(name, cache):
        return {"checked": True, "status": "dissolved"}

    monkeypatch.setattr(sos, "_lookup_nc_sos", fake_lookup)
    li = _biz(1)
    asyncio.run(sos.enrich_with_sos_dissolution([li], max_check=5))
    assert li.raw.get("sos_dissolution") == li.raw.get("sos_status")
    assert li.raw["sos_dissolution"]["status"] == "dissolved"


def test_active_status_not_tagged(monkeypatch):
    async def fake_lookup(name, cache):
        return {"checked": True, "status": "active"}

    monkeypatch.setattr(sos, "_lookup_nc_sos", fake_lookup)
    li = _biz(1)
    asyncio.run(sos.enrich_with_sos_dissolution([li], max_check=5))
    assert "sos_status" not in (li.raw or {})
    assert "sos_dissolution" not in (li.raw or {})


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


def test_is_business_no_substring_false_positives():
    """Regression for the bug found live 2026-10-02: the old _is_business()
    was a bare `any(marker in name.lower() for marker in MARKERS)` substring
    scan, so "inc" and "lp" (unanchored) matched ordinary surnames/given
    names -- "Vincent", "Lincoln", "Prince", "Alphonso", "Randolph",
    "Delphine" all contain one of those substrings. A live board audit
    (docs/listings.json) found 7,552 defendant/owner_name row occurrences
    (2,065 unique names) misclassified this way. _is_business() now defers
    to name_normalize.is_entity(), the word-boundary-safe token check this
    codebase already uses for the same question everywhere else."""
    not_businesses = [
        "Vincent, James", "John Vincent", "Lincoln, Mary", "Mary Lincoln",
        "St Vincent de Paul", "Randolph, Carter", "Alphonso Gaines",
        "Delphine Walton", "Prince, Keisha", "Anderson Myron Vincent",
    ]
    for name in not_businesses:
        assert sos._is_business(name) is False, f"{name!r} is a person, not a business"

    real_businesses = [
        "Smith LLC", "Jones Inc", "Principal Investments LLC", "Marcos Inc",
        "Smith Corp", "ABC Co", "Acme Holdings LLC",
    ]
    for name in real_businesses:
        assert sos._is_business(name) is True, f"{name!r} should still read as a business"
