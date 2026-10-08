"""qPayBill delinquent roll: every county is swept every run, stalest first, and nothing read is
thrown away when the scraper's own soft timeout fires.

Audit 2026-10-09 (source_completeness), measured on the gated VM run of 2026-10-08: the scraper's
fixed timeout_s=900 let 11 of 29 counties finish (name order, 4 at a time), then cancelled fetch();
the other 18 counties' sweeps were never awaited again, ran on for 40 more minutes, and every row
they read was dropped. The same cut happened on every run, so 25,314 of the source's 33,180 rows
on the 10/7 board had not been re-read since mid-September and the staged detail pass never ran.

Fixtures are made up (no network). Each test fails on the code before the fix.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.counties_sc import qpaybill_delinquent_roll as mod
from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import QPayBillDelinquentRoll


def _row(ident: str, county: str, href: bool = False) -> dict:
    r = {"notice_no": f"N-{county}-{ident}", "owner": f"SAMPLE OWNER {ident}",
         "address": f"{ident} EXAMPLE ST", "year": "2024", "description": "SAMPLE",
         "ident": ident, "status": "Unpaid", "amount": 250.0}
    if href:
        r["detail_href"] = f"TaxesDetailsType4.aspx?receiptNo={ident}&x=1"
    return r


def _stats() -> dict:
    return dict(queries=1, errors=0, page_capped_prefixes=0, pager_stalled=0, drifted=0,
                deepened=0, truncated_prefixes=0, lost_prefixes=[])


def _absorb(sink, stats, rows):
    if sink is not None:
        for r in rows:
            sink[(r["ident"], r.get("year") or "", r.get("notice_no") or "")] = r
    if stats is not None:
        stats.update(_stats())


def _fresh_sems(monkeypatch, concurrent: int = 4):
    monkeypatch.setattr(mod, "MAX_CONCURRENT_COUNTIES", concurrent)
    monkeypatch.setattr(mod, "_COUNTY_SEM", None)
    monkeypatch.setattr(mod, "_GLOBAL_SEM", None)


def test_scraper_timeout_covers_a_full_sweep_of_every_county():
    waves = -(-len(mod.QPAYBILL_SUBS) // mod.MAX_CONCURRENT_COUNTIES)
    need = mod.COUNTY_TIMEOUT_S * waves + mod.DETAIL_BUDGET_S
    assert QPayBillDelinquentRoll.timeout_s >= need, (
        f"timeout_s={QPayBillDelinquentRoll.timeout_s} cannot fit {waves} waves of "
        f"{mod.COUNTY_TIMEOUT_S}s plus the detail pass ({need}s): counties late in the order "
        f"are cut on every run")
    assert mod.full_sweep_timeout_s(29, per_county_s=480, concurrent=4, detail_s=900) == 4860.0


def test_the_stalest_county_is_swept_first(monkeypatch):
    subs = {"Alpha": "alpha", "Bravo": "bravo", "Charlie": "charlie", "Delta": "delta"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "STALE_FIRST", True)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 5.0)
    _fresh_sems(monkeypatch, concurrent=1)
    freshness = {"Alpha": "2026-10-06", "Bravo": "2026-09-10", "Charlie": "2026-09-14"}
    monkeypatch.setattr(mod, "board_plan_and_freshness", lambda path=None: ({}, freshness))
    started: list[str] = []

    async def fake(client, county, sub, budget, sink=None, stats=None):
        started.append(county)
        rows = [_row(f"{county[0]}1", county)]
        _absorb(sink, stats, rows)
        return rows, stats

    monkeypatch.setattr(mod, "sweep_county", fake)
    out = asyncio.run(asyncio.wait_for(QPayBillDelinquentRoll().fetch(), timeout=5.0))
    # Delta has no board rows (never read): first; then oldest freshest-row first.
    assert started == ["Delta", "Bravo", "Charlie", "Alpha"]
    assert {li.county for li in out} == set(subs)


def test_county_order_helper():
    assert mod.county_order(["B", "A", "C"], {"A": "2026-10-06", "B": "2026-09-10"}) == ["C", "B", "A"]
    assert mod.county_order(["B", "A"], {}) == ["A", "B"]


def test_a_scraper_timeout_ships_what_unfinished_counties_already_read(monkeypatch):
    subs = {"Fast": "fast", "Slow": "slow"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 30.0)          # the per-county bound is NOT what fires
    monkeypatch.setattr(QPayBillDelinquentRoll, "timeout_s", 0.3)
    monkeypatch.setattr(mod, "board_plan_and_freshness", lambda path=None: ({}, {}), raising=False)
    _fresh_sems(monkeypatch)

    async def fake(client, county, sub, budget, sink=None, stats=None):
        if county == "Fast":
            rows = [_row("F1", county)]
            _absorb(sink, stats, rows)
            return rows, stats
        # Slow reads two parcels, then is still walking prefixes when the scraper gives up.
        _absorb(sink, stats, [_row("S1", county), _row("S2", county)])
        await asyncio.sleep(10)
        return list(sink.values()), stats

    monkeypatch.setattr(mod, "sweep_county", fake)
    scraper = QPayBillDelinquentRoll()
    out = asyncio.run(scraper.safe_run())
    assert scraper.last_outcome == OUTCOME_PARTIAL
    assert sorted(li.parcel_id for li in out) == ["F1", "S1", "S2"], (
        "rows the unfinished county had already read must ship, not be dropped")


def test_unfinished_sweeps_are_cancelled_when_the_scraper_gives_up(monkeypatch):
    subs = {"Fast": "fast", "Slow": "slow"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 30.0)
    monkeypatch.setattr(QPayBillDelinquentRoll, "timeout_s", 0.2)
    monkeypatch.setattr(mod, "board_plan_and_freshness", lambda path=None: ({}, {}), raising=False)
    _fresh_sems(monkeypatch)
    state = {"slow_cancelled": False}

    async def fake(client, county, sub, budget, sink=None, stats=None):
        if county == "Fast":
            rows = [_row("F1", county)]
            _absorb(sink, stats, rows)
            return rows, stats
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            state["slow_cancelled"] = True
            raise
        return [], stats

    monkeypatch.setattr(mod, "sweep_county", fake)

    async def main():
        out = await QPayBillDelinquentRoll().safe_run()
        await asyncio.sleep(0.05)   # let a cancelled task run its handler
        return out, state["slow_cancelled"]

    out, cancelled = asyncio.run(main())
    assert [li.parcel_id for li in out] == ["F1"]
    assert cancelled, "the unfinished county's sweep kept running after the scraper gave up"


def test_the_prefix_walk_start_rotates_by_day_and_still_covers_every_prefix():
    a = mod.frontier_order(date(2026, 10, 9))
    b = mod.frontier_order(date(2026, 10, 10))
    assert sorted(a) == sorted(mod._ALPHABET) == sorted(b)
    assert a[0] != b[0], "a fixed start cuts the same late letters on every timed-out run"


def test_details_parsed_before_the_detail_deadline_are_kept(monkeypatch):
    subs = {"Alpha": "alpha"}
    monkeypatch.setattr(mod, "QPAYBILL_SUBS", subs)
    monkeypatch.setattr(mod, "COUNTY_TIMEOUT_S", 5.0)
    monkeypatch.setattr(mod, "DETAIL_ENABLED", True)
    monkeypatch.setattr(mod, "DETAIL_BUDGET_S", 0.3)
    monkeypatch.setattr(QPayBillDelinquentRoll, "timeout_s", 120.0)
    monkeypatch.setattr(mod, "board_plan_and_freshness", lambda path=None: ({}, {}))
    _fresh_sems(monkeypatch)
    rows = [_row("A1", "Alpha", href=True), _row("A2", "Alpha", href=True)]

    async def fake(client, county, sub, budget, sink=None, stats=None):
        _absorb(sink, stats, rows)
        return list(rows), stats

    async def fake_details(client, sub, hrefs, stats, pace_s=None, got=None):
        got = {} if got is None else got
        got["A1" if "A1" in hrefs[0] else "A2"] = {"appraised_value": 12345.0}
        await asyncio.sleep(10)          # the second detail never arrives before the deadline
        return got

    monkeypatch.setattr(mod, "sweep_county", fake)
    monkeypatch.setattr(mod, "fetch_details_paced", fake_details)
    out = asyncio.run(asyncio.wait_for(QPayBillDelinquentRoll().fetch(), timeout=5.0))
    assert len(out) == 2
    detailed = [li for li in out if (li.raw.get("qpaybill_roll") or {}).get("detail")]
    assert len(detailed) == 1, "the detail parsed before the deadline must be kept"


def test_freshness_is_the_median_so_a_few_merged_rows_do_not_hide_a_stale_county(monkeypatch):
    import foreclosure_scraper.board_stream as bs
    src = "counties_sc.qpaybill_delinquent_roll"

    def row(county, seen, ident):
        return {"source": src, "county": county, "last_seen": f"{seen}T00:00:00",
                "raw": {"qpaybill_roll": {"identification_no": ident, "county": county}}}

    rows = ([row("Kershaw", "2026-09-14", f"K{i}") for i in range(9)] + [row("Kershaw", "2026-10-06", "K9")]
            + [row("Dillon", "2026-10-06", f"D{i}") for i in range(3)] + [row("Mccormick", "2026-09-10", "M1")])
    monkeypatch.setattr(bs, "iter_board_rows", lambda path=None: iter(rows))
    plan, fr = mod.board_plan_and_freshness("unused")
    assert fr == {"kershaw": "2026-09-14", "dillon": "2026-10-06", "mccormick": "2026-09-10"}
    assert len(plan) == 14
    assert mod.county_order(["Dillon", "Kershaw", "McCormick", "Lee"], fr) == ["Lee", "McCormick", "Kershaw", "Dillon"]
