"""qPayBill delinquent roll: one hung county must never zero out the other 18.

ROOT CAUSE, CONFIRMED BY TRACING (not assumed), full run 2026-09-23: the scraper hit
its own timeout_s=900.0 (TIMEOUT after exactly 901s) and captured ZERO fresh rows
across ALL 19 counties -- not "the stuck county got 0 rows", every county did,
including ones that almost certainly finished in the first minute.

The old fetch() ran:

    results = await asyncio.gather(*(sweep_county(...) for county, sub in ...))
    for (county, _sub), res in zip(sorted(targets.items()), results):
        ...build `out`...

so nothing was collected into `out` until EVERY county's sweep_county() coroutine had
resolved. base_scraper.safe_run() wraps the whole fetch() in
``asyncio.wait_for(self._collect(), timeout=self.timeout_s)``; when that fired while
the gather() was still waiting on one slow county, it cancelled fetch() before the
`for` loop that builds `out` ever ran -- discarding the 18 counties that HAD already
finished along with the one that had not. fetch() also never wrote to self.partial,
which is base_scraper's own documented timeout-salvage mechanism ("A scraper that
appends here as it goes will have that work SHIPPED if the soft timeout fires"), so
safe_run()'s TimeoutError handler had nothing to salvage either.

REQUEST_BUDGET_PER_COUNTY bounds how many requests a county can spend, not how long
it can take doing it, so a portal that answers slowly without ever raising an
exception -- Williamsburg has repeatedly hit GenericErrorPage.aspx in production
logs -- could occupy a worker for the scraper's entire 900s soft timeout on its own,
and nothing upstream of the fix below stopped it.

THE FIX has two parts, and these tests exercise both independently:

  1. Each county's sweep_county() call is now wrapped in its own
     ``asyncio.wait_for(..., timeout=COUNTY_TIMEOUT_S)`` (see COUNTY_TIMEOUT_S's
     docstring in the source module), so one hung county can no longer consume the
     whole scraper budget by itself -- it is abandoned and reported as failed instead.
  2. fetch() now processes each county's result via ``asyncio.as_completed`` and
     appends its listings to ``self.partial`` AS EACH COUNTY FINISHES, rather than
     building `out` only after one big gather() resolves. That is what lets
     base_scraper.safe_run()'s existing timeout-salvage path actually ship something
     if the scraper-level timeout ever fires anyway.
"""
from __future__ import annotations

import asyncio
import time

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.counties_sc import qpaybill_delinquent_roll as mod
from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (
    QPayBillDelinquentRoll,
)


def _row(ident, county):
    """A minimal but realistic raw grid row, same shape parse_grid() produces."""
    return {"notice_no": f"N-{county}-{ident}", "owner": f"OWNER {ident}",
            "address": f"{ident} MAIN ST", "year": "2024",
            "description": "PROP OF X", "ident": ident, "status": "Unpaid",
            "amount": 250.0}


def _empty_stats(**extra) -> dict:
    return dict(queries=1, errors=0, page_capped_prefixes=0, pager_stalled=0,
                drifted=0, deepened=0, truncated_prefixes=0, lost_prefixes=[], **extra)


def _make_fake_sweep_county(*, delays: dict, rows_by_county: dict):
    """Stands in for the real sweep_county(): no HTTP, just a controllable delay
    per county plus a fixed row set, so these tests exercise fetch()'s own
    orchestration logic rather than the portal's HTML parsing (already covered by
    tests/test_qpaybill_delinquent_roll.py)."""
    async def fake(client, county, sub, budget):
        delay = delays.get(county, 0.0)
        if delay:
            await asyncio.sleep(delay)
        return list(rows_by_county.get(county, [])), _empty_stats()
    return fake


# ---------------------------------------------------------------------------
# (a) one simulated county hangs -> the others still come back, not zero
# ---------------------------------------------------------------------------

def test_one_hung_county_does_not_zero_out_the_other_counties(monkeypatch):
    """MEASURED (simulated): with a per-county timeout of 0.05s, a county whose
    sweep_county() never returns inside that window must be dropped -- and dropped
    WITHOUT blocking the other counties' real, already-collected rows from coming
    back. Before the fix, this scenario reproduced the live 2026-09-23 failure:
    fetch() awaited one gather() over every county, so a county that never resolves
    meant fetch() never resolves either, and this test would hang forever rather
    than complete with the two good counties' rows."""
    subs = {"Fast1": "fast1treasurer", "Fast2": "fast2treasurer", "Stuck": "stucktreasurer"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 0.05)

    rows_by_county = {
        "Fast1": [_row("001", "Fast1")],
        "Fast2": [_row("002", "Fast2"), _row("003", "Fast2")],
        "Stuck": [_row("999", "Stuck")],   # would be real data IF the county ever answered
    }
    fake = _make_fake_sweep_county(delays={"Stuck": 3600.0}, rows_by_county=rows_by_county)
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()
    # Outer safety net only -- if the per-county timeout regresses, this fails loud
    # (as a timeout) instead of hanging the whole test suite.
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    counties_present = {li.county for li in out}
    assert counties_present == {"Fast1", "Fast2"}, (
        "the stuck county must be dropped, but Fast1/Fast2 must still be present -- "
        "a scraper-wide zero, or losing the good counties, is the bug this fixes")
    assert len(out) == 3


def test_the_hung_county_is_abandoned_within_its_own_timeout_not_the_scrapers(monkeypatch):
    """The per-county bound must actually be enforced, not just present in name.
    Measured: with COUNTY_TIMEOUT_S=0.05 and a county that sleeps for an hour,
    fetch() as a whole must return in a small multiple of 0.05s, not in anything
    close to timeout_s (900s in production)."""
    subs = {"Solo": "solotreasurer"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 0.05)
    fake = _make_fake_sweep_county(delays={"Solo": 3600.0}, rows_by_county={})
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()

    async def _timed():
        start = time.monotonic()
        out = await scraper.fetch()
        return out, time.monotonic() - start

    out, elapsed = asyncio.run(asyncio.wait_for(_timed(), timeout=5.0))
    assert out == []
    assert elapsed < 2.0, (
        f"fetch() took {elapsed:.2f}s to abandon a single hung county with "
        f"COUNTY_TIMEOUT_S=0.05 -- the per-county bound is not being enforced")


# ---------------------------------------------------------------------------
# (b) normal run, everyone succeeds -> unchanged behavior
# ---------------------------------------------------------------------------

def test_a_clean_run_with_every_county_succeeding_is_unchanged(monkeypatch):
    """Restructuring fetch() to salvage per-county must not change what a healthy
    run produces: same counties, same parcels, same aggregation. Order across
    counties is no longer guaranteed (asyncio.as_completed processes whichever
    county finishes first, not sorted alphabetical order), so this asserts content,
    not list order."""
    subs = {"Alpha": "alphatreasurer", "Beta": "betatreasurer", "Gamma": "gammatreasurer"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 30.0)

    rows_by_county = {
        "Alpha": [_row("A1", "Alpha")],
        "Beta": [_row("B1", "Beta"), _row("B2", "Beta")],
        "Gamma": [_row("G1", "Gamma"), _row("G2", "Gamma"), _row("G3", "Gamma")],
    }
    fake = _make_fake_sweep_county(delays={}, rows_by_county=rows_by_county)
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert len(out) == 6
    by_county = {}
    for li in out:
        by_county.setdefault(li.county, []).append(li)
    assert {c: len(v) for c, v in by_county.items()} == {"Alpha": 1, "Beta": 2, "Gamma": 3}
    idents = {li.parcel_id for li in out}
    assert idents == {"A1", "B1", "B2", "G1", "G2", "G3"}


def test_self_partial_mirrors_the_returned_listings_on_a_clean_run(monkeypatch):
    """self.partial is now populated incrementally as the salvage mechanism for
    base_scraper.safe_run(). On a run that completes normally (no timeout), it must
    end up holding exactly what fetch() returned -- proving the incremental
    population doesn't drop or duplicate anything even when nothing goes wrong."""
    subs = {"Alpha": "alphatreasurer", "Beta": "betatreasurer"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 30.0)
    rows_by_county = {"Alpha": [_row("A1", "Alpha")], "Beta": [_row("B1", "Beta")]}
    fake = _make_fake_sweep_county(delays={}, rows_by_county=rows_by_county)
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert {li.parcel_id for li in scraper.partial} == {li.parcel_id for li in out}
    assert len(scraper.partial) == len(out) == 2


# ---------------------------------------------------------------------------
# The real regression: proven at the safe_run() layer, matching the exact
# 2026-09-23 failure mode (scraper-level soft timeout firing mid-sweep).
# ---------------------------------------------------------------------------

def test_safe_run_salvages_finished_counties_when_the_scraper_level_timeout_fires(monkeypatch):
    """This is the actual bug, reproduced end-to-end through base_scraper.safe_run():
    a scraper-level soft timeout fires while one county is still running. Before the
    fix, safe_run()'s TimeoutError handler found self.partial empty (fetch() never
    touched it) and reported OUTCOME_TIMEOUT with 0 rows -- exactly the live
    2026-09-23 failure ("TIMEOUT after exactly 901s", 0 rows for all 19 counties).

    COUNTY_TIMEOUT_S is set well ABOVE the scraper's own timeout_s here, so the
    per-county guard (fix part 1) is deliberately NOT what saves this test -- it
    isolates fix part 2 (as_completed + self.partial) as the thing standing between
    a slow county and a zero-row run.
    """
    subs = {"Fast": "fasttreasurer", "Slow": "slowtreasurer"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 30.0)   # far above timeout_s below
    monkeypatch.setattr(QPayBillDelinquentRoll, "timeout_s", 0.15)

    rows_by_county = {"Fast": [_row("F1", "Fast")], "Slow": [_row("S1", "Slow")]}
    fake = _make_fake_sweep_county(delays={"Slow": 5.0}, rows_by_county=rows_by_county)
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()
    out = asyncio.run(scraper.safe_run())

    assert scraper.last_outcome == OUTCOME_PARTIAL, (
        f"expected the Fast county's row to be salvaged as PARTIAL, got "
        f"{scraper.last_outcome!r} ({scraper.last_reason!r}) -- this is the exact "
        f"shape of the live 2026-09-23 all-zero failure")
    assert len(out) == 1
    assert out[0].county == "Fast"
    assert out[0].parcel_id == "F1"
