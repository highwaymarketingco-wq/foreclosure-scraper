"""Pin the hard caps on enrich_with_aggressive_address.

Run #16 spent 3h 21m on a single step (aggressive_address) before the user
cancelled. There was no wall-clock cap, no per-listing timeout, no max-
targets cap. With ~100 unaddressed listings × 46 SC counties × 3 name
permutations per county = 13,800+ HTTP queries, even at 0.5s each that's
nearly 2 hours; many GIS endpoints take 1-3s.

These tests verify:
  1. MAX_TARGETS cap actually limits how many listings are processed
  2. Wall-clock cap actually fires (using a fast monkeypatched body)
  3. Per-listing timeout actually fires when a single listing hangs
  4. Already-addressed listings are skipped
  5. Bankruptcy-source listings are skipped
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, defendant: str, state: str = "SC", source: str = "x", **kw) -> Listing:
    base = dict(
        source=source,
        source_url=f"https://example.com/{defendant.replace(' ', '_')}",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        defendant=defendant,
        state=state,
        county="Spartanburg" if state == "SC" else "Mecklenburg",
        street_address=None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


@pytest.mark.asyncio
async def test_max_targets_cap_applies():
    """If 100 listings need addresses, only MAX_TARGETS get processed.
    We mock the body so it's fast — the assertion is on counts['queried']."""
    from foreclosure_scraper import enrichment_aggressive_address as agg

    listings = [_li(defendant=f"Person {i}") for i in range(100)]

    queried = []

    async def fake_run_one(c, li, cache, counts):
        queried.append(li.defendant)
        counts["no_match"] += 1

    with patch.dict(os.environ, {
        "AGGRESSIVE_ADDR_MAX_TARGETS": "10",
        "AGGRESSIVE_ADDR_WALL_CLOCK_S": "60",
        "AGGRESSIVE_ADDR_PER_LISTING_S": "5",
    }), patch.object(agg, "_run_one_listing", fake_run_one):
        await agg.enrich_with_aggressive_address(listings)

    assert len(queried) == 10, f"expected 10 processed, got {len(queried)}"


@pytest.mark.asyncio
async def test_wall_clock_cap_fires():
    """A long-running body must be cancelled when wall-clock budget expires.
    We use a 1s wall clock and a 60s body — gather should be cancelled
    at ~1s, not 60s."""
    from foreclosure_scraper import enrichment_aggressive_address as agg

    listings = [_li(defendant=f"Slow Person {i}") for i in range(5)]

    async def slow_run_one(c, li, cache, counts):
        await asyncio.sleep(60)  # would exceed wall clock
        counts["no_match"] += 1

    with patch.dict(os.environ, {
        "AGGRESSIVE_ADDR_MAX_TARGETS": "100",
        "AGGRESSIVE_ADDR_WALL_CLOCK_S": "1",   # 1s budget
        "AGGRESSIVE_ADDR_PER_LISTING_S": "30",
    }), patch.object(agg, "_run_one_listing", slow_run_one):
        t0 = time.monotonic()
        await agg.enrich_with_aggressive_address(listings)
        elapsed = time.monotonic() - t0

    # Should bail at ~1s wall-clock, not anywhere near 60s. Generous upper
    # bound for slow CI runners.
    assert elapsed < 5.0, f"wall-clock cap didn't fire — elapsed {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_per_listing_timeout_fires():
    """A single hanging listing must not consume more than PER_LISTING_S
    seconds. The other listings still get processed."""
    from foreclosure_scraper import enrichment_aggressive_address as agg

    listings = [_li(defendant=f"P{i}") for i in range(3)]

    async def hang_first_run_fast_others(c, li, cache, counts):
        if li.defendant == "P0":
            await asyncio.sleep(60)  # hang
        else:
            counts["no_match"] += 1

    with patch.dict(os.environ, {
        "AGGRESSIVE_ADDR_MAX_TARGETS": "100",
        "AGGRESSIVE_ADDR_WALL_CLOCK_S": "60",
        "AGGRESSIVE_ADDR_PER_LISTING_S": "1",   # 1s per-listing
    }), patch.object(agg, "_run_one_listing", hang_first_run_fast_others):
        t0 = time.monotonic()
        await agg.enrich_with_aggressive_address(listings)
        elapsed = time.monotonic() - t0

    # P0 hung but timed out at ~1s. P1, P2 succeeded. Total wall < 5s.
    assert elapsed < 5.0, f"per-listing timeout didn't fire — elapsed {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_skips_already_addressed():
    """Listings with a street_address don't enter the target list."""
    from foreclosure_scraper import enrichment_aggressive_address as agg
    listings = [
        _li(defendant="Already Addressed",
            street_address="123 Main St"),  # has address → skip
        _li(defendant="Needs Address"),
    ]
    queried = []

    async def fake(c, li, cache, counts):
        queried.append(li.defendant)
        counts["no_match"] += 1

    with patch.object(agg, "_run_one_listing", fake):
        await agg.enrich_with_aggressive_address(listings)
    assert queried == ["Needs Address"]


@pytest.mark.asyncio
async def test_skips_courtlistener_bankruptcy():
    """Bankruptcy listings have a different enrichment path (bk_property);
    the aggressive scan is wrong for them and would burn budget."""
    from foreclosure_scraper import enrichment_aggressive_address as agg
    listings = [
        _li(defendant="BK Defendant",
            source="national.courtlistener_bankruptcy"),
        _li(defendant="Regular Defendant"),
    ]
    queried = []

    async def fake(c, li, cache, counts):
        queried.append(li.defendant)
        counts["no_match"] += 1

    with patch.object(agg, "_run_one_listing", fake):
        await agg.enrich_with_aggressive_address(listings)
    assert queried == ["Regular Defendant"]


@pytest.mark.asyncio
async def test_prioritizes_by_soonest_sale_date():
    """When MAX_TARGETS clips, the listings with soonest sale_date win.
    Investor priority: imminent sales matter more than amorphous ones."""
    from foreclosure_scraper import enrichment_aggressive_address as agg
    soon = datetime.utcnow() + timedelta(days=3)
    later = datetime.utcnow() + timedelta(days=60)
    listings = [
        _li(defendant="Later Sale", sale_date=later),
        _li(defendant="Soon Sale", sale_date=soon),
        _li(defendant="No Sale Date", sale_date=None),
    ]

    queried = []

    async def fake(c, li, cache, counts):
        queried.append(li.defendant)
        counts["no_match"] += 1

    with patch.dict(os.environ, {"AGGRESSIVE_ADDR_MAX_TARGETS": "1"}), \
            patch.object(agg, "_run_one_listing", fake):
        await agg.enrich_with_aggressive_address(listings)
    assert queried == ["Soon Sale"], (
        "soonest-sale priority broken — "
        f"got {queried}, expected ['Soon Sale']"
    )
