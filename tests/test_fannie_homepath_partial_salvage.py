"""FannieHomePath.fetch(): a stuck bbox cell must not zero out the cells that
already finished, and a scraper-level soft timeout must salvage whatever was
already collected instead of discarding it.

MEASURED 2026-09-22/23 (logs/local-run-20260922T111425.log lines 41-224;
docs/full_run_execution_audit_2026-09-23.md, section "fannie_homepath fix --
did it behave as expected?"): this scraper's own soft timeout_s=150 deadline
did NOT fire on schedule during the 2026-09-22 main scrape phase -- scraper.
start was 15:14:34.475753Z, scraper.timeout was 15:23:19.851313Z, 8m45s later.
In that whole window exactly one other event source (national.
foreclosure_dot_com, running sequential per-city fetches for ~8 minutes
straight) logged anything at all; every other in-flight scraper -- including
this one's own remaining SC bbox cells -- produced NO log output until
foreclosure_dot_com finally finished, at which point four scrapers' timeouts
(this one included) and several scraper.start events all fired within the same
~50ms. That is event-loop starvation by a sibling scraper, not this scraper
needing more time to run: by 15:15:01 (27s in) it had already cleanly fetched
all 16 NC cells (~6,000+ rows) plus the first SC cell -- comfortably inside
even the OLD 60s budget -- and then simply never got scheduled again until it
was cancelled.

Fixing the starvation itself is out of this file's scope (an
orchestrator/sibling-scraper concern; this task may only touch
fannie_homepath.py + the freshness-pruning module). The fixable bug in THIS
file: the old fetch() awaited one asyncio.gather() per state and only appended
to `out` after EVERY cell in that state resolved, so a cancellation mid-gather
discarded cells that had already succeeded, and fetch() never touched
self.partial (base_scraper's own documented timeout-salvage mechanism -- "A
scraper that appends here as it goes will have that work SHIPPED if the soft
timeout fires"), so safe_run()'s TimeoutError handler had nothing to ship
either.

These tests mirror tests/test_qpaybill_county_timeout_salvage.py's proven
pattern for the identical class of bug in a sibling scraper.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.national import fannie_homepath as hp
from foreclosure_scraper.scrapers.national.fannie_homepath import FannieHomePath


def _listing(n: int) -> Listing:
    return Listing(
        source=FannieHomePath.slug,
        source_url=f"https://homepath.fanniemae.com/property/uuid-{n}",
        listing_type=ListingType.REO,
        state="NC",
        street_address=f"{n} Test St",
        case_number=f"fannie-uuid-{n}",
    )


def _make_fake_fetch_indexed(*, delays: dict, rows_by_index: dict):
    """Stands in for the real _fetch_bbox_indexed(): no HTTP, just a
    controllable delay per cell index plus a fixed row set -- exercises
    fetch()'s own per-cell salvage logic, not the Fannie JSON parsing (already
    covered elsewhere in this repo's fixtures for this scraper)."""
    async def fake(i, state, cell, slug):
        delay = delays.get(i, 0.0)
        if delay:
            await asyncio.sleep(delay)
        return i, list(rows_by_index.get(i, []))
    return fake


def test_one_stuck_cell_does_not_zero_out_the_cells_that_already_finished(monkeypatch):
    """MEASURED (simulated): a cell that never resolves within the test's outer
    cutoff must be dropped -- WITHOUT blocking the cells that already succeeded
    from coming back. Before the fix, fetch() awaited one gather() over every
    cell in a state, so one stuck cell meant fetch() never resolved at all --
    exactly the shape of the live starvation failure (SC cells past the first
    two never logged bbox_done, and the scraper as a whole produced nothing)."""
    monkeypatch.setattr(hp, "BBOXES", (("NC", 0.0, 0.0, 1.0, 1.0),))
    monkeypatch.setattr(hp, "_subdivide", lambda *a, **k: [0, 1, 2])

    rows_by_index = {0: [_listing(0)], 1: [_listing(1)], 2: [_listing(2)]}
    fake = _make_fake_fetch_indexed(delays={2: 3600.0}, rows_by_index=rows_by_index)
    monkeypatch.setattr(hp, "_fetch_bbox_indexed", fake)

    scraper = FannieHomePath()
    scraper.timeout_s = 0.2
    out = asyncio.run(scraper.safe_run())

    case_numbers = {li.case_number for li in out}
    assert case_numbers == {"fannie-uuid-0", "fannie-uuid-1"}, (
        "the stuck cell must be dropped, but cells 0 and 1 must still be present -- "
        "a scraper-wide zero, or losing the good cells, is the bug this fixes")
    assert scraper.last_outcome == OUTCOME_PARTIAL


def test_a_clean_run_with_every_cell_succeeding_is_unchanged(monkeypatch):
    """Restructuring fetch() to salvage per-cell must not change what a healthy
    run produces. Order is no longer guaranteed (asyncio.as_completed yields
    whichever cell finishes first), so this asserts content, not list order,
    and confirms the existing case_number dedup still collapses the repeat
    rows that recur when the two states re-run the same fake cell indices."""
    monkeypatch.setattr(hp, "BBOXES", (("NC", 0.0, 0.0, 1.0, 1.0), ("SC", 0.0, 0.0, 1.0, 1.0)))
    monkeypatch.setattr(hp, "_subdivide", lambda *a, **k: [0, 1])

    rows_by_index = {0: [_listing(0)], 1: [_listing(1)]}
    fake = _make_fake_fetch_indexed(delays={}, rows_by_index=rows_by_index)
    monkeypatch.setattr(hp, "_fetch_bbox_indexed", fake)

    scraper = FannieHomePath()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert {li.case_number for li in out} == {"fannie-uuid-0", "fannie-uuid-1"}
    assert len(out) == 2


def test_self_partial_mirrors_the_returned_listings_on_a_clean_run(monkeypatch):
    """self.partial is now populated incrementally as the salvage mechanism for
    base_scraper.safe_run(). On a run that completes normally (no timeout), it
    must hold exactly what fetch() returned -- proving the incremental
    population doesn't drop or duplicate anything even when nothing goes wrong."""
    monkeypatch.setattr(hp, "BBOXES", (("NC", 0.0, 0.0, 1.0, 1.0),))
    monkeypatch.setattr(hp, "_subdivide", lambda *a, **k: [0, 1])

    rows_by_index = {0: [_listing(0)], 1: [_listing(1)]}
    fake = _make_fake_fetch_indexed(delays={}, rows_by_index=rows_by_index)
    monkeypatch.setattr(hp, "_fetch_bbox_indexed", fake)

    scraper = FannieHomePath()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert {li.case_number for li in scraper.partial} == {li.case_number for li in out}
    assert len(scraper.partial) == len(out) == 2


def test_safe_run_salvages_finished_cells_when_the_scraper_level_timeout_fires(monkeypatch):
    """The actual bug, reproduced end-to-end through base_scraper.safe_run(): a
    scraper-level soft timeout fires while one cell is still running. Before
    the fix, safe_run()'s TimeoutError handler found self.partial empty
    (fetch() never touched it) and reported OUTCOME_TIMEOUT with 0 rows -- the
    same shape as the live 2026-09-22 all-zero failure (scraper.timeout at
    15:23:19.851313Z with nothing salvaged, discarding the 16 NC cells that
    had already succeeded)."""
    monkeypatch.setattr(hp, "BBOXES", (("NC", 0.0, 0.0, 1.0, 1.0),))
    monkeypatch.setattr(hp, "_subdivide", lambda *a, **k: [0, 1])

    rows_by_index = {0: [_listing(0)], 1: [_listing(1)]}
    fake = _make_fake_fetch_indexed(delays={1: 3600.0}, rows_by_index=rows_by_index)
    monkeypatch.setattr(hp, "_fetch_bbox_indexed", fake)

    scraper = FannieHomePath()
    scraper.timeout_s = 0.15
    out = asyncio.run(scraper.safe_run())

    assert scraper.last_outcome == OUTCOME_PARTIAL, (
        f"expected cell 0's row to be salvaged as PARTIAL, got "
        f"{scraper.last_outcome!r} ({scraper.last_reason!r}) -- this is the exact "
        f"shape of the live 2026-09-22 all-zero timeout")
    assert len(out) == 1
    assert out[0].case_number == "fannie-uuid-0"
