"""zombie_properties.fetch() must not block the asyncio event loop.

MEASURED live 2026-09-23/24 in logs/local-run-20260923T194338.log: this
scraper's fetch() calls the fully synchronous load_board() (gzip decompress
+ json.loads of docs/listings.json, ~1.1GB, plus Listing.model_validate() on
~193K rows) and then runs a synchronous grouping/analysis loop over the whole
board -- with no `await` anywhere in the call chain. A coroutine with zero
await points cannot be preempted by asyncio.wait_for (Task cancellation only
takes effect at an await), so this ran to completion regardless of its own
timeout_s=120.0 and froze the ENTIRE event loop for its whole duration: the
live log shows this scraper running 23:55:53Z-00:37:43Z (41m50s) with ZERO
log lines from ANY other scraper anywhere in that window, then 10+ sibling
scrapers' timeouts (plus all 27 of counties_sc.qpaybill_delinquent_roll's own
per-county timeouts) firing within an 800ms window the instant this scraper
finally returned -- because nothing else got scheduler time to make progress
while it ran. This is the same starvation mechanism independently confirmed
in national.foreclosure_dot_com for the 2026-09-22/23 run's
national.fannie_homepath incident (docs/full_run_execution_audit_2026-09-23.md).

Fix: run the synchronous body in a worker thread via asyncio.to_thread, so
the event loop stays free for sibling scrapers even while this one is busy.
This test proves the event loop is genuinely free during fetch() by racing
a concurrent asyncio.sleep()-based "heartbeat" counter against it -- on the
old (blocking) code this heartbeat would never increment until fetch()
returned; on the fix it increments throughout.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc.zombie_properties import ZombieProperties


def _li(**kw):
    base = dict(
        source="test", source_url="https://x/y", state="SC", county="Anderson",
        listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.SINGLE_FAMILY,
        parcel_id="123", street_address="1 Main St",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def _synthetic_board(n: int) -> list[Listing]:
    """n old, unresolved lis pendens rows -- enough real work that the
    synchronous grouping loop takes measurable wall-clock time, so a still-
    blocked event loop would visibly starve the heartbeat below."""
    old = datetime.utcnow() - timedelta(days=400)
    return [
        _li(parcel_id=f"P{i}", street_address=f"{i} Old Mill Rd", first_seen=old)
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_fetch_does_not_block_the_event_loop():
    board = _synthetic_board(20_000)  # enough rows to take real time to group/scan
    heartbeats = {"n": 0}

    async def _heartbeat():
        while True:
            await asyncio.sleep(0.01)
            heartbeats["n"] += 1

    with patch("foreclosure_scraper.web_artifact.load_board", return_value=board):
        hb_task = asyncio.create_task(_heartbeat())
        scraper = ZombieProperties()
        await scraper.fetch()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    # On the old (blocking) code, fetch() never yields, so the heartbeat task
    # -- scheduled on the SAME event loop -- gets zero chances to run until
    # fetch() has already returned, i.e. heartbeats["n"] would be 0 (or at
    # best 1, from a single tick squeezed in before/after). asyncio.to_thread
    # keeps the loop free the whole time fetch() is doing real work, so the
    # heartbeat should have ticked many times over.
    assert heartbeats["n"] > 3, (
        f"only {heartbeats['n']} heartbeats ticked while fetch() ran -- "
        "the event loop was blocked, the fix regressed"
    )


@pytest.mark.asyncio
async def test_fetch_still_finds_real_zombies_after_the_threading_change():
    """Functional-equivalence guard: moving the body into a worker thread via
    asyncio.to_thread must not change WHAT gets detected, only how it's
    scheduled."""
    old = datetime.utcnow() - timedelta(days=400)
    recent = datetime.utcnow() - timedelta(days=10)
    zombie_lp = _li(parcel_id="Z1", street_address="1 Stalled Ln", first_seen=old)
    resolved_lp = _li(parcel_id="Z2", street_address="2 Dismissed Ln", first_seen=old,
                       auction_status="dismissed")
    progressed_lp = _li(parcel_id="Z3", street_address="3 Sold Ln", first_seen=old)
    progressed_sale = _li(parcel_id="Z3", street_address="3 Sold Ln", first_seen=old,
                           listing_type=ListingType.FORECLOSURE_SALE)
    too_recent_lp = _li(parcel_id="Z4", street_address="4 New Ln", first_seen=recent)
    board = [zombie_lp, resolved_lp, progressed_lp, progressed_sale, too_recent_lp]

    with patch("foreclosure_scraper.web_artifact.load_board", return_value=board):
        scraper = ZombieProperties()
        out = await scraper.fetch()

    addresses = {li.street_address for li in out}
    assert addresses == {"1 Stalled Ln"}
    assert out[0].listing_type == ListingType.DISTRESSED
    assert out[0].source == "counties_sc.zombie_properties"


@pytest.mark.asyncio
async def test_fetch_handles_board_load_failure_without_blocking():
    with patch("foreclosure_scraper.web_artifact.load_board", side_effect=RuntimeError("boom")):
        scraper = ZombieProperties()
        out = await scraper.fetch()
    assert out == []
