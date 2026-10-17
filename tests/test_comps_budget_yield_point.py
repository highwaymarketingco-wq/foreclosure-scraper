"""Comps phase budget fix (gap-sweep wave 2, 2026-10-16).

Audit finding: `enrich_with_comps()`'s per-listing loop has no await point for the vast
majority of rows (the GIS sale-price cross-check path is rare), so `main.py`'s
`asyncio.wait_for(..., timeout=COMPS_PHASE_MAX_SECONDS)` could not actually preempt the
loop near its stated budget -- live production logs showed 100-700s of overshoot past the
cap. Fix: yield (`await asyncio.sleep(0)`) every 200 rows so the event loop gets a chance
to raise the timeout close to the real deadline instead of only after the whole,
potentially 437k-row, loop finishes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper import enrichment_comps as ec
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _listing(state, county, **kw):
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state=state, county=county,
        living_sqft=1500, bedrooms=3,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def test_the_loop_yields_periodically_not_only_at_the_very_end(monkeypatch):
    monkeypatch.setattr(ec, "_sold_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 0)

    yields = {"n": 0}
    real_sleep = asyncio.sleep

    async def counting_sleep(secs):
        if secs == 0:
            yields["n"] += 1
        await real_sleep(secs)

    monkeypatch.setattr(ec.asyncio, "sleep", counting_sleep)

    listings = [_listing("NC", "Catawba") for _ in range(450)]
    asyncio.run(ec.enrich_with_comps(listings))

    # 450 rows at one yield per 200 -> rows 0, 200, 400 -> 3 yields.
    assert yields["n"] == 3


def test_a_small_batch_under_the_yield_threshold_still_completes_and_matches(monkeypatch):
    """The yield point must not change WHICH rows get matched -- only when control is
    handed back to the event loop. A batch smaller than 200 still runs its one yield at
    row 0 and still produces a correct comp."""
    sold_record = dict(
        street="1 Hickory Ln", city="Hickory", state="NC", zip_code="28601",
        sold_price=250000, sqft=1500, beds=3, full_baths=2,
        year_built=2005, lot_sqft=8000, last_sold_date="2026-05-01",
        style="Single Family", property_url="http://example.test/1",
    )
    monkeypatch.setattr(ec, "_sold_pool_for_seat", lambda c, s: [dict(sold_record)])
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 5)

    subj = _listing("NC", "Catawba", zip_code="28601")
    asyncio.run(ec.enrich_with_comps([subj]))

    assert subj.raw.get("comps"), "yield point must not break comp matching for a small batch"
    assert subj.raw["comps"][0]["address"] == "1 Hickory Ln"


def test_wait_for_can_actually_preempt_mid_loop(monkeypatch):
    """The whole point of the fix: a timeout armed around enrich_with_comps() must be able
    to fire before the loop would otherwise finish, given enough rows and a short enough
    timeout, because there is now a real await point for the scheduler to act on."""
    monkeypatch.setattr(ec, "_sold_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 0)

    completed = {"done": False}

    async def run_and_mark():
        await ec.enrich_with_comps([_listing("NC", "Catawba") for _ in range(1000)])
        completed["done"] = True

    async def main():
        try:
            await asyncio.wait_for(run_and_mark(), timeout=0.001)
        except asyncio.TimeoutError:
            pass

    asyncio.run(main())
    assert completed["done"] is False, "timeout should have preempted before the loop finished"
