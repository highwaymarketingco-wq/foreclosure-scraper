"""Berkeley County SC paystar.io tax source: one slow detail request must not zero
out the ones that already finished, and a scraper-level soft timeout must salvage
whatever was already collected instead of discarding it.

ROOT CAUSE, MEASURED live 2026-09-23 (plain httpx, no browser, no CAPTCHA/WAF hit at
any point): the 2026-09-23 full run hit this scraper's own timeout_s=300.0 (TIMEOUT
after exactly 300s) and captured ZERO fresh rows despite real progress happening
underneath. The old fetch() awaited ONE ``asyncio.gather()`` over every invoice's
detail request and only built the `out` list from ``zip(rows, details)`` AFTER that
gather() resolved. base_scraper.safe_run() wraps the whole fetch() in
``asyncio.wait_for(self._collect(), timeout=self.timeout_s)``; when that fired while
the gather() was still waiting on the slower invoices, it cancelled fetch() before the
`out`-building loop ever ran, discarding every listing already parsed along with the
ones still in flight. fetch() also never wrote to self.partial, which is
base_scraper's own documented timeout-salvage mechanism ("A scraper that appends here
as it goes will have that work SHIPPED if the soft timeout fires"), so safe_run()'s
TimeoutError handler had nothing to ship either.

Live investigation (>5,000 real detail requests against berkeleycountysc.paystar.io
across several probes) found NO single pathologically-stuck request -- every request
eventually returned, 0 real errors. This is a DIFFERENT root cause than the sibling
qpaybill_delinquent_roll.py bug (a Williamsburg county request that could hang
indefinitely): here the vendor is genuinely just slow at scale, and the roll had also
grown from 2,310 to 3,426 rows since the 2026-09-23 run:

    concurrency=10 (unchanged from before this fix): 2,200/3,426 details in 270.6s
        (8.1 req/s sustained) -> extrapolates to ~420s for the full roll
    concurrency=20 (tried, then reverted): 3,000/3,426 details in 330.3s (9.1 req/s
        sustained -- barely better despite 2x the concurrency), and the LAST 300 of
        those slowed to 3.9 req/s -- worse than concurrency=10's pace at a comparable
        cumulative request count, consistent with server-side backpressure kicking in
        under higher sustained load rather than a client-side bottleneck. Concurrency
        was left at 10 rather than risk provoking harsher throttling from a small
        county vendor for no reliable throughput gain.

THE FIX has two parts, and these tests exercise both independently:

  1. timeout_s raised 300.0 -> 600.0: comfortable margin over the ~420-450s measured/
     extrapolated full-roll time (see class docstring in the source module), still
     well inside the 900s ceiling already used by the heaviest county_tax source in
     this same directory (greenville_hard_distress.py).
  2. fetch() now consumes each invoice's detail fetch via ``asyncio.as_completed`` and
     appends its parsed Listing to ``self.partial`` AS EACH ONE FINISHES, rather than
     building `out` only after one big gather() resolves. That is what lets
     base_scraper.safe_run()'s existing timeout-salvage path actually ship something
     if the scraper-level timeout ever fires anyway (e.g. the roll keeps growing, or
     the vendor slows down further).

These tests mirror tests/test_qpaybill_county_timeout_salvage.py's and
tests/test_fannie_homepath_partial_salvage.py's proven pattern for the identical
class of bug in sibling scrapers.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.counties_sc import berkeley_paystar_tax as mod
from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import (
    BerkeleyPaystarTax,
)


def _detail(ident: str, amount_cents: int = 10000) -> dict:
    """A minimal but realistic invoice detail, same shape _detail_to_listing() needs
    to produce a non-None Listing (real fixture shape covered by
    tests/test_berkeley_paystar_tax.py; this is deliberately bare-bones since these
    tests exercise fetch()'s own orchestration logic, not the detail parsing)."""
    return {
        "invoiceNumber": f"INV-{ident}",
        "taxYear": 2025,
        "invoiceAmountMinor": amount_cents,
        "delinquent": True,
        "invoiceeName": f"OWNER {ident}",
        "invoiceStreetAddress1": "1 MAIN ST",
        "invoiceCity": "TESTCITY",
        "invoiceState": "SC",
        "invoicePostalCode": "29401",
        "assetIdentifierDisplay": f"PARCEL-{ident}",
        "assetOwner": f"OWNER {ident}",
        "assetMetaJson": None,
    }


def _make_fake_list_all(hashes):
    async def fake(client):
        return [{"invoiceNumberHash": h} for h in hashes]
    return fake


def _make_fake_fetch_detail(*, delays: dict, details_by_hash: dict):
    """Stands in for the real _fetch_detail(): no HTTP, just a controllable delay
    per invoice hash plus a fixed detail payload -- exercises fetch()'s own
    orchestration logic rather than the portal's JSON shape (already covered by
    tests/test_berkeley_paystar_tax.py)."""
    async def fake(client, sem, invoice_hash):
        delay = delays.get(invoice_hash, 0.0)
        if delay:
            await asyncio.sleep(delay)
        return invoice_hash, details_by_hash.get(invoice_hash)
    return fake


# ---------------------------------------------------------------------------
# (a) one simulated slow/stuck detail request -> the others still come back, not zero
# ---------------------------------------------------------------------------

def test_one_stuck_detail_does_not_zero_out_the_details_that_already_finished(monkeypatch):
    """MEASURED (simulated), through safe_run(): unlike qpaybill's sweep_county() (an
    unbounded internal loop), each Berkeley detail fetch is a single httpx GET already
    bounded by the client's own timeout=30.0 -- so nothing INSIDE fetch() needs its own
    per-item wait_for. The thing under test here is that the SCRAPER-level soft timeout
    (safe_run's asyncio.wait_for) can fire while one invoice is still in flight, and the
    invoices that already finished must survive that -- not just the single-survivor
    case covered by test_safe_run_salvages_finished_details_... below."""
    hashes = ["fast1", "fast2", "stuck"]
    monkeypatch.setattr(mod, "_list_all", _make_fake_list_all(hashes))

    details_by_hash = {
        "fast1": _detail("F1"),
        "fast2": _detail("F2"),
        "stuck": _detail("S1"),   # would be real data IF the request ever answered
    }
    fake = _make_fake_fetch_detail(delays={"stuck": 3600.0}, details_by_hash=details_by_hash)
    monkeypatch.setattr(mod, "_fetch_detail", fake)
    monkeypatch.setattr(BerkeleyPaystarTax, "timeout_s", 0.2)

    scraper = BerkeleyPaystarTax()
    out = asyncio.run(scraper.safe_run())

    parcels_present = {li.parcel_id for li in out}
    assert parcels_present == {"PARCEL-F1", "PARCEL-F2"}, (
        "the stuck invoice must be dropped, but F1/F2 must still be present -- "
        "a scraper-wide zero, or losing the good invoices, is the bug this fixes")
    assert len(out) == 2
    assert scraper.last_outcome == OUTCOME_PARTIAL


# ---------------------------------------------------------------------------
# (b) normal run, everyone succeeds -> unchanged behavior
# ---------------------------------------------------------------------------

def test_a_clean_run_with_every_detail_succeeding_is_unchanged(monkeypatch):
    """Restructuring fetch() to salvage per-invoice must not change what a healthy
    run produces: same invoices, same parcels. Order is no longer guaranteed
    (asyncio.as_completed yields whichever detail finishes first), so this asserts
    content, not list order."""
    hashes = ["h1", "h2", "h3"]
    monkeypatch.setattr(mod, "_list_all", _make_fake_list_all(hashes))

    details_by_hash = {"h1": _detail("A1"), "h2": _detail("A2"), "h3": _detail("A3")}
    fake = _make_fake_fetch_detail(delays={}, details_by_hash=details_by_hash)
    monkeypatch.setattr(mod, "_fetch_detail", fake)

    scraper = BerkeleyPaystarTax()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert len(out) == 3
    assert {li.parcel_id for li in out} == {"PARCEL-A1", "PARCEL-A2", "PARCEL-A3"}


def test_self_partial_mirrors_the_returned_listings_on_a_clean_run(monkeypatch):
    """self.partial is now populated incrementally as the salvage mechanism for
    base_scraper.safe_run(). On a run that completes normally (no timeout), it must
    end up holding exactly what fetch() returned -- proving the incremental
    population doesn't drop or duplicate anything even when nothing goes wrong."""
    hashes = ["h1", "h2"]
    monkeypatch.setattr(mod, "_list_all", _make_fake_list_all(hashes))

    details_by_hash = {"h1": _detail("A1"), "h2": _detail("A2")}
    fake = _make_fake_fetch_detail(delays={}, details_by_hash=details_by_hash)
    monkeypatch.setattr(mod, "_fetch_detail", fake)

    scraper = BerkeleyPaystarTax()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert {li.parcel_id for li in scraper.partial} == {li.parcel_id for li in out}
    assert len(scraper.partial) == len(out) == 2


# ---------------------------------------------------------------------------
# The real regression: proven at the safe_run() layer, matching the exact
# 2026-09-23 failure mode (scraper-level soft timeout firing mid-detail-fetch).
# ---------------------------------------------------------------------------

def test_safe_run_salvages_finished_details_when_the_scraper_level_timeout_fires(monkeypatch):
    """This is the actual bug, reproduced end-to-end through base_scraper.safe_run():
    a scraper-level soft timeout fires while some detail requests are still running.
    Before the fix, safe_run()'s TimeoutError handler found self.partial empty
    (fetch() never touched it) and reported OUTCOME_TIMEOUT with 0 rows -- exactly
    the live 2026-09-23 failure (TIMEOUT after exactly 300s, 0 fresh rows despite a
    2,310+ row board source with real progress happening underneath)."""
    hashes = ["fast", "slow"]
    monkeypatch.setattr(mod, "_list_all", _make_fake_list_all(hashes))

    details_by_hash = {"fast": _detail("F1"), "slow": _detail("S1")}
    fake = _make_fake_fetch_detail(delays={"slow": 5.0}, details_by_hash=details_by_hash)
    monkeypatch.setattr(mod, "_fetch_detail", fake)
    monkeypatch.setattr(BerkeleyPaystarTax, "timeout_s", 0.15)

    scraper = BerkeleyPaystarTax()
    out = asyncio.run(scraper.safe_run())

    assert scraper.last_outcome == OUTCOME_PARTIAL, (
        f"expected the fast invoice's row to be salvaged as PARTIAL, got "
        f"{scraper.last_outcome!r} ({scraper.last_reason!r}) -- this is the exact "
        f"shape of the live 2026-09-23 all-zero timeout")
    assert len(out) == 1
    assert out[0].parcel_id == "PARCEL-F1"


# ---------------------------------------------------------------------------
# timeout_s itself: pinned to the measured floor/ceiling, not an arbitrary guess.
# ---------------------------------------------------------------------------

def test_timeout_is_comfortably_above_the_measured_full_roll_extrapolation():
    # measured: concurrency=10 sustained 8.1 req/s across 2,200 real detail requests,
    # extrapolating to ~420s for the full 3,426-row roll (and the roll only grows).
    # 600s is not "any bigger number" -- it is a floor with real margin over that
    # extrapolation, not just clearing the old (too-small) 300s.
    assert BerkeleyPaystarTax.timeout_s >= 450.0


def test_timeout_stays_within_this_directory_established_ceiling():
    # greenville_hard_distress.py (same counties_sc directory) already runs at
    # timeout_s=900.0 for a comparably heavy source; this scraper's budget should
    # stay a fraction of that, not approach or exceed the established heaviest case.
    assert BerkeleyPaystarTax.timeout_s <= 900.0
