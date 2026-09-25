"""qPayBill delinquent roll: one hung county must never zero out the other 18, AND
launching every county at once must never starve them ALL.

ROOT CAUSE #1, CONFIRMED BY TRACING (not assumed), full run 2026-09-23: the scraper hit
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

THE FIX for #1 has two parts:

  1. Each county's sweep_county() call is now wrapped in its own
     ``asyncio.wait_for(..., timeout=COUNTY_TIMEOUT_S)`` (see COUNTY_TIMEOUT_S's
     docstring in the source module), so one hung county can no longer consume the
     whole scraper budget by itself -- it is abandoned and reported as failed instead.
  2. fetch() now processes each county's result via ``asyncio.as_completed`` and
     appends its listings to ``self.partial`` AS EACH COUNTY FINISHES, rather than
     building `out` only after one big gather() resolves. That is what lets
     base_scraper.safe_run()'s existing timeout-salvage path actually ship something
     if the scraper-level timeout ever fires anyway.

ROOT CAUSE #2, CONFIRMED LIVE 2026-09-25 (two days after the above landed, once the
roster grew from 19 to 29 counties): fixing #1 did not fix a DIFFERENT failure. A real
``--slugs counties_sc.qpaybill_delinquent_roll`` run reported ALL 29 configured
counties hitting qpaybill_roll.county_timeout, every one logging errors=1 queries=0 --
not one stuck county, EVERY county, including ones that (measured live, alone, same
day) finish in well under a minute.

MEASURED against the live vendor with the real (unmocked) sweep_county()):
  * Lee ALONE: 46.27s wall clock, 225 queries, 0 errors -- comfortably under
    COUNTY_TIMEOUT_S=480s, and its throughput (4.86 req/s) matches the historical
    19-county CONCURRENT run's aggregate rate almost exactly (26,750 requests /
    5,581s = 4.79 req/s, logs/qpaybill_roll_all.log, 2026-09-10) -- i.e. the shared
    12-slot _GLOBAL_SEM was never actually delivering more aggregate throughput than
    ONE county got alone, once enough counties piled onto it.
  * 8 small/medium counties launched CONCURRENTLY, old fetch() shape
    (_GLOBAL_CONCURRENCY=12, no per-county gate): more than 3 minutes wall clock with
    ZERO of the 8 complete -- not slower, STARVED.

MECHANISM: the old fetch() used asyncio.ensure_future over EVERY target county at
once, and each county's OWN sweep_county() immediately fans out to up to 36
concurrent prefix walks for its depth-1 frontier (asyncio.gather over
guarded(p) for p in _ALPHABET). With N counties doing this simultaneously, up to
N x 36 "guarded" coroutines (1,044 at N=29) compete for _GLOBAL_SEM's slots from the
first tick, and each slot is held for a WHOLE prefix walk (viewstate GET + search
POST + however many page POSTs that letter needs), not one request. No county was
ever guaranteed a fair share, and at N=29 essentially nobody got one inside
COUNTY_TIMEOUT_S.

THE FIX for #2 has THREE parts, and each later one was found only by MEASURING the
previous one's effect against the live vendor rather than assuming it was enough:

  1. MAX_CONCURRENT_COUNTIES (see its docstring in the source module) caps how many
     counties may be ACTIVELY inside sweep_county() at once -- acquired via a new
     ``_county_sem()`` in run_county(), BEFORE the existing per-county
     ``asyncio.wait_for(..., COUNTY_TIMEOUT_S)`` starts its clock, so queueing time
     for a slot is never charged against a county's own timeout budget.
     _GLOBAL_CONCURRENCY was also raised 12 -> 24 (burst-tested live: 24 concurrent
     GETs across 8 hosts and 15 concurrent GETs against one host both returned
     all-200 in ~1.5s, no throttling). First tried at MAX_CONCURRENT_COUNTIES=8,
     matching 8 x _PER_HOST_CONCURRENCY (3) == _GLOBAL_CONCURRENCY (24) exactly.
  2. That sizing identity only holds if a single county can never have more than
     _PER_HOST_CONCURRENCY of its own prefix walks contending for a GLOBAL slot at
     once -- and it could: guarded() acquired ``_global_sem(), sem`` in that order
     (global THEN per-host), so a county's depth-1 frontier (up to 36 prefixes)
     submitted 36 simultaneous attempts on the scarce global semaphore, even though
     only 3 could ever do anything useful (gated by its own per-host `sem`
     immediately after). The other up-to-33 sat there HOLDING a global slot while
     blocked on their OWN county's per-host cap -- pure waste, and re-measuring
     part 1 alone confirmed it: 8 real counties at that exact-match sizing still took
     far longer than 8 independent 46s solo runs would predict. Swapping the
     acquisition order to ``sem, _global_sem()`` (per-host first) fixed the waste: a
     county can now never have more than 3 coroutines contending for a global slot.
  3. Even after part 2, re-testing the SAME 8 counties at the SAME 8/24 exact-match
     sizing still left 4 of 8 unfinished past 500s -- fetch()'s county gate is a
     ROLLING window (29 counties queue behind 8 lanes in production), so the instant
     one active county finishes, a queued one immediately fills the slot, and a
     straggler from the first batch never actually gets relief. Lowering
     MAX_CONCURRENT_COUNTIES to 4 (12 of the 24 global slots, real headroom instead
     of an exact match) measured ~1.8x faster completion for the same two counties
     (Lee 313.9s -> 175.7s, Union 324.9s -> 188.3s).

The tests below exercise fix #1 (one hung county), fix #2 part 1 (many counties at
once), fix #2 part 2 (the semaphore-order waste inside ONE county), and fix #2 part 3
(headroom over an exact match), plus the clean-run and safe_run-salvage paths that
must stay unchanged.
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


# ---------------------------------------------------------------------------
# (c) the 2026-09-25 regression: many counties launched AT ONCE must not starve
# every one of them -- fix #2 (MAX_CONCURRENT_COUNTIES / _county_sem()).
# ---------------------------------------------------------------------------

def _make_tracking_fake_sweep_county(*, work_s: float, peak: dict, rows_by_county: dict):
    """Like _make_fake_sweep_county, but tracks PEAK CONCURRENT invocations so a test
    can prove the county-level gate actually bounds how many run at once, not just
    that they all eventually finish (which asyncio.gather would also do with zero
    gating -- concurrency has to be observed, not inferred from the end state)."""
    active = 0
    lock = asyncio.Lock()

    async def fake(client, county, sub, budget):
        nonlocal active
        async with lock:
            active += 1
            peak["value"] = max(peak["value"], active)
        try:
            if work_s:
                await asyncio.sleep(work_s)
            return list(rows_by_county.get(county, [_row(f"{county}1", county)])), _empty_stats()
        finally:
            async with lock:
                active -= 1
    return fake


def test_many_counties_launched_at_once_does_not_starve_every_one_of_them(monkeypatch):
    """MEASURED root cause of the 2026-09-25 incident: the OLD fetch() launched every
    target county via asyncio.ensure_future at once, so N counties' sweep_county()
    calls all competed for the same request-level semaphore from the first tick, and
    at N=29 that starved literally all of them past COUNTY_TIMEOUT_S -- confirmed live
    (see module docstring): 8 real counties launched together produced ZERO
    completions in 3+ minutes, against a 46s solo baseline for the smallest one alone.

    This test proves the fix at the fetch()-orchestration level, without hitting the
    network: with MAX_CONCURRENT_COUNTIES patched to 3 and 10 counties configured,
    (a) no more than 3 are ever active in sweep_county() at the same instant, and
    (b) all 10 still complete -- the gate throttles, it does not drop anyone.
    """
    subs = {f"C{i}": f"c{i}treasurer" for i in range(10)}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 5.0)
    monkeypatch.setattr(mod, "MAX_CONCURRENT_COUNTIES", 3)
    monkeypatch.setattr(mod, "_COUNTY_SEM", None)  # force a fresh semaphore at this size

    peak = {"value": 0}
    fake = _make_tracking_fake_sweep_county(work_s=0.05, peak=peak, rows_by_county={})
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert peak["value"] <= 3, (
        f"peak concurrent sweep_county() calls was {peak['value']}, expected <= 3 -- "
        f"MAX_CONCURRENT_COUNTIES is not actually gating entry, which is exactly the "
        f"un-gated shape that reproduced the 2026-09-25 all-29-counties-timeout failure")
    assert {li.county for li in out} == set(subs), (
        "gating concurrency must not drop any county -- every one of the 10 must "
        "still complete, just not all AT ONCE")
    assert len(out) == 10


def test_queueing_for_a_county_slot_is_not_charged_against_that_countys_own_timeout(monkeypatch):
    """The county-level gate is acquired BEFORE run_county()'s own
    asyncio.wait_for(..., COUNTY_TIMEOUT_S) starts its clock. If it were charged
    instead, throttling concurrency would just move the starvation from "every county
    times out because the request-level semaphore is oversubscribed" to "every county
    times out because it spent its whole per-county budget waiting in the queue for a
    slot" -- a different-looking but equally total failure.

    MAX_CONCURRENT_COUNTIES=1 forces full serialization; 4 counties each need 0.1s of
    ACTUAL work, comfortably under COUNTY_TIMEOUT_S=0.3s individually, but the queue
    means the 4th county doesn't start its own work until ~0.3s of wall clock have
    already passed waiting for the first three. If queueing time counted against its
    timeout, it would already be over budget before doing a single unit of work; since
    it does not, all four must still succeed.
    """
    subs = {"A": "a", "B": "b", "C": "c", "D": "d"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 0.3)
    monkeypatch.setattr(mod, "MAX_CONCURRENT_COUNTIES", 1)
    monkeypatch.setattr(mod, "_COUNTY_SEM", None)

    peak = {"value": 0}
    fake = _make_tracking_fake_sweep_county(work_s=0.1, peak=peak, rows_by_county={})
    monkeypatch.setattr(mod, "sweep_county", fake)

    scraper = QPayBillDelinquentRoll()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert peak["value"] == 1, "MAX_CONCURRENT_COUNTIES=1 must fully serialize the sweeps"
    counties_present = {li.county for li in out}
    assert counties_present == set(subs), (
        f"only {counties_present} completed -- a county queued behind others must not "
        f"be timed out for time spent WAITING for a slot, only for its own active sweep")


def test_max_concurrent_counties_leaves_headroom_under_global_concurrency(monkeypatch):
    """Locks in the sizing relationship the module docstring argues for, AFTER the
    2026-09-25 tuning: an ACTIVE county's worst-case global-slot demand
    (MAX_CONCURRENT_COUNTIES x _PER_HOST_CONCURRENCY) must stay COMFORTABLY under
    _GLOBAL_CONCURRENCY, not merely equal to it.

    This used to assert an EXACT match (8 x 3 == 24) on the theory that an active
    county would then see the same global-semaphore pressure it saw running alone.
    MEASURED live the same day that theory was incomplete: re-testing the same 8
    counties at that exact-match sizing still left 4 of 8 unfinished past 500s,
    because fetch()'s county gate is a ROLLING window -- the instant one active county
    finishes, a queued one (29 total in production) immediately fills the slot, so a
    straggler never gets the slack exact-match sizing implicitly assumed it would.
    Lowering MAX_CONCURRENT_COUNTIES to leave real headroom (4 x 3 = 12 of 24, not
    24 of 24) measured ~1.8x faster completion for the same two counties (Lee 313.9s
    -> 175.7s, Union 324.9s -> 188.3s). A future change that erases this headroom
    should fail loudly here rather than silently reintroducing that straggling."""
    demand = mod.MAX_CONCURRENT_COUNTIES * mod._PER_HOST_CONCURRENCY
    assert demand < mod._GLOBAL_CONCURRENCY, (
        f"worst-case per-active-county global-slot demand ({demand}) is not comfortably "
        f"under _GLOBAL_CONCURRENCY ({mod._GLOBAL_CONCURRENCY}) -- an exact match was "
        f"MEASURED to still starve stragglers under fetch()'s rolling county gate")


# ---------------------------------------------------------------------------
# (d) fix #2 part 2: a SINGLE county must never hold more global-semaphore slots
# than it can actually use, or MAX_CONCURRENT_COUNTIES' sizing math is fiction.
# ---------------------------------------------------------------------------

def test_one_county_never_holds_more_global_slots_than_its_own_per_host_cap(monkeypatch):
    """MEASURED regression, same day: applying ONLY the MAX_CONCURRENT_COUNTIES gate
    (fix #2 part 1) and re-testing the same 8 real counties still ran far slower than
    8 independent solo runs would predict, even though _GLOBAL_CONCURRENCY (24) was
    sized to exactly match MAX_CONCURRENT_COUNTIES x _PER_HOST_CONCURRENCY. Tracing
    why: sweep_county()'s guarded() acquired ``_global_sem(), sem`` in that order
    (global THEN per-host). A county's depth-1 frontier submits up to 36 simultaneous
    guarded() calls via asyncio.gather() -- ALL 36 raced for a GLOBAL slot at once,
    even though only _PER_HOST_CONCURRENCY (3) could ever proceed past this county's
    OWN per-host semaphore. The rest sat there holding a scarce global slot they could
    not use, silently defeating the MAX_CONCURRENT_COUNTIES x _PER_HOST_CONCURRENCY ==
    _GLOBAL_CONCURRENCY sizing identity from the inside.

    This test exercises sweep_county() itself (not a fetch()-level mock), with
    _walk_prefix faked out so it needs no network. Measuring concurrency INSIDE
    _walk_prefix would not catch this bug -- that number is bounded by BOTH
    semaphores together regardless of which is acquired first, so it looks identical
    for the buggy and fixed order. What differs is how many prefix walks are
    simultaneously HOLDING a global slot (whether or not they can also proceed past
    their own per-host cap) -- so this instruments _global_sem() itself: a fresh,
    generously-sized (50 >> 3) real semaphore wrapped to record peak concurrent
    holders. With the old ``_global_sem(), sem`` order, a county's full 36-letter
    frontier (submitted at once via asyncio.gather()) would grab up to 36 global
    slots instantly (50 is enough for all of them) even though only 3 could ever do
    anything useful -- peak would read up to 36. With the fixed ``sem, _global_sem()``
    order, a county can never have more than _PER_HOST_CONCURRENCY coroutines even
    ATTEMPTING to acquire a global slot, so peak must stay <= 3 however large the
    global cap is.
    """
    real_sem = asyncio.Semaphore(50)
    peak = {"value": 0}
    held = {"value": 0}
    lock = asyncio.Lock()

    class _TrackingSem:
        async def __aenter__(self):
            await real_sem.acquire()
            async with lock:
                held["value"] += 1
                peak["value"] = max(peak["value"], held["value"])
            return self

        async def __aexit__(self, *exc):
            async with lock:
                held["value"] -= 1
            real_sem.release()

    tracking = _TrackingSem()
    monkeypatch.setattr(mod, "_global_sem", lambda: tracking)

    async def fake_walk_prefix(client, sub, prefix, budget, sink, stats):
        await asyncio.sleep(0.02)
        return False, set()   # no deepening needed -- keeps this a single gather()

    monkeypatch.setattr(mod, "_walk_prefix", fake_walk_prefix)

    budget = mod._Budget(10_000)
    rows, stats = asyncio.run(asyncio.wait_for(
        mod.sweep_county(None, "Solo", "solotreasurer", budget), timeout=5.0))

    assert peak["value"] <= mod._PER_HOST_CONCURRENCY, (
        f"peak concurrent prefix walks HOLDING a global slot was {peak['value']}, "
        f"expected <= _PER_HOST_CONCURRENCY ({mod._PER_HOST_CONCURRENCY}) even though "
        f"the global cap (50) could easily have let all 36 of this county's depth-1 "
        f"prefixes hold one at once -- that over-acquisition is exactly the waste "
        f"that defeated MAX_CONCURRENT_COUNTIES' sizing math on 2026-09-25")
