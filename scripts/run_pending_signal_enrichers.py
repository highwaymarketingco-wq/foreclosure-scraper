#!/usr/bin/env python3
"""Run the raw-key enrichers wired into main.py after the last full pipeline
landing, directly against the existing board -- WITHOUT a full scrape-everything
main.py pass.

WHY THIS EXISTS
    docs/completeness_audit_2026-09-29.md, Section 6: 8 signals were wired into
    main.py's run() between 2026-09-28 19:59 and 2026-09-29 12:47 (evening of
    the last full landing, commit 7f78473a, through the morning after) and show
    0 live rows on the board -- not because they're broken, but because no full
    main.py pass has executed since they were wired. All 8 are either pure
    compute over raw fields ALREADY on the board (no new scrape needed) or free/
    keyless public-API enrichers that already run this same way elsewhere in the
    pipeline (see scripts/catchup_failed_enrichers.py, scripts/enrich_gaps.py --
    this script is the same shape, generalized to this batch):

        liensnc_posthumous_filing   enrichment_liensnc_posthumous  (offline join)
        platted_lots                enrichment_platted_lots        (offline regex)
        divorce_no_subsequent_deed  enrichment_divorce_no_subsequent_deed (offline join)
        notice_service_defect       enrichment_notice_service_defect      (offline join)
        jail_booking_new            enrichment_jail_bookings       (free county roster APIs)
        bop_federal                 enrichment_bop_federal         (free bop.gov, keyless)
        landlocked + cemetery_proximity  enrichment_land_buildability (free NC OneMap ArcGIS)
        repeat_foreclosure_filing   enrichment_foreclosure_docket_history (offline sidecar join)

    NOT included: heir_naming_publication. That one is a SCRAPER
    (counties.column_legal_notices' SC quiet-title parsing), not an enrichment
    tag -- it needs scripts/run_scoped_scrapers.py --slugs counties.column_legal_notices
    instead, which actually fetches new notices. Running it here would do nothing
    (this script never scrapes).

USAGE
    python3 scripts/run_pending_signal_enrichers.py [--dry-run] [--only KEY ...]

    Refuses to run while the engine or another board writer looks to be running.
    Run it under the board lock, same as any board writer:

        scripts/with_board_lock.sh pending_signal_enrichers -- \\
            .venv/bin/python scripts/run_pending_signal_enrichers.py

    --dry-run loads the board, runs every step, prints before/after counts, and
    writes nothing. Same idempotence guarantee as the enrichers themselves: a
    second run only adds newly-eligible rows (a fresh jail booking, a newly
    parsed platted-lot description), it never un-tags or duplicates a hit.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402
from foreclosure_scraper.main import _await_capped  # noqa: E402

STEPS = [
    "liensnc_posthumous",
    "platted_lots",
    "divorce_no_subsequent_deed",
    "notice_service_defect",
    "jail_bookings",
    "bop_federal",
    "land_buildability",
    "foreclosure_docket_history",
]

# raw keys this script reports on (one step can stamp more than one key)
RAW_KEYS = [
    "liensnc_posthumous_filing",
    "platted_lots",
    "divorce_no_subsequent_deed",
    "notice_service_defect",
    "jail_booking_new",
    "bop_federal",
    "landlocked",
    "cemetery_proximity",
    "repeat_foreclosure_filing",
]


def _engine_running() -> bool:
    # The pattern must not begin with "-": pgrep reads a leading dash as an
    # option, matches nothing, and the guard silently never fires.
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _truthy(v) -> bool:
    return v not in (None, "", [], {})


def _counts(listings) -> dict:
    out: dict = {}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        for k in RAW_KEYS:
            if _truthy(raw.get(k)):
                out[k] = out.get(k, 0) + 1
    return out


async def _run_one(name: str, listings: list) -> dict:
    if name == "liensnc_posthumous":
        from foreclosure_scraper.enrichment_liensnc_posthumous import enrich_liensnc_posthumous
        return enrich_liensnc_posthumous(listings) or {}
    if name == "platted_lots":
        from foreclosure_scraper.enrichment_platted_lots import enrich_platted_lots
        return enrich_platted_lots(listings) or {}
    if name == "divorce_no_subsequent_deed":
        from foreclosure_scraper.enrichment_divorce_no_subsequent_deed import (
            enrich_divorce_no_subsequent_deed,
        )
        return enrich_divorce_no_subsequent_deed(listings) or {}
    if name == "notice_service_defect":
        from foreclosure_scraper.enrichment_notice_service_defect import enrich_notice_service_defect
        return enrich_notice_service_defect(listings) or {}
    if name == "jail_bookings":
        from foreclosure_scraper.enrichment_jail_bookings import enrich_jail_bookings
        return await _await_capped(enrich_jail_bookings(listings), "jail_bookings") or {}
    if name == "bop_federal":
        from foreclosure_scraper.enrichment_bop_federal import enrich_bop_federal
        return await _await_capped(enrich_bop_federal(listings), "bop_federal") or {}
    if name == "land_buildability":
        from foreclosure_scraper.enrichment_land_buildability import enrich_land_buildability
        return await _await_capped(enrich_land_buildability(listings), "land_buildability") or {}
    if name == "foreclosure_docket_history":
        from foreclosure_scraper.enrichment_foreclosure_docket_history import (
            enrich_foreclosure_docket_history,
        )
        return await _await_capped(
            enrich_foreclosure_docket_history(listings), "foreclosure_docket_history") or {}
    raise ValueError(f"unknown step {name!r}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", action="append", choices=STEPS,
                    help="run just these steps (default: all)")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    which = args.only or STEPS
    t0 = time.time()
    listings = load_board()
    print(f"board: {len(listings):,} leads ({time.time() - t0:.1f}s load)", flush=True)
    before = _counts(listings)
    print(f"before: {before}", flush=True)

    stats: dict[str, dict] = {}
    for name in which:
        print(f"\n--- {name}", flush=True)
        t1 = time.time()
        try:
            stats[name] = await _run_one(name, listings)
            print(f"    {stats[name]}  ({time.time() - t1:.1f}s)", flush=True)
        except Exception as exc:  # noqa: BLE001 - one enricher must not stop the rest
            print(f"    FAILED: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
            stats[name] = {"failed": f"{type(exc).__name__}: {str(exc)[:200]}"}

    after = _counts(listings)
    print("\n=== before -> after (delta) ===", flush=True)
    for k in RAW_KEYS:
        b, a = before.get(k, 0), after.get(k, 0)
        print(f"  {k}: {b} -> {a} (+{a - b})", flush=True)

    if args.dry_run:
        print("\ndry run -- board not written", flush=True)
        return 0

    lp, _ = write_artifact(
        listings, {"notes": f"pending signal enrichers (2026-09-29 audit follow-up): {', '.join(which)}"})
    print(f"\nwrote {lp}: {len(listings):,} leads", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
