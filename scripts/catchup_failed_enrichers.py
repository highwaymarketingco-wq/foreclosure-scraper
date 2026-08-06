#!/usr/bin/env python3
"""Re-run enrichers that died mid-run, against the published board.

WHY THIS EXISTS
    On 2026-08-04 three enrichers died on an ImportError caused by editing the
    codebase while the 30-hour run was live: the orchestrator held a stale
    module object, so newly-added names were missing when later lazily-imported
    files asked for them. Root cause is fixed (mailing_shape.py), but that run
    still shipped without them:

        incarceration   owner in custody -> a hard motivation signal
        jail_bookings   county booking rosters
        skip_trace      PHONE NUMBERS — the contactability path

    Losing skip_trace matters most: a lead with a deadline and no phone is not
    actionable, which is exactly the gap the dashboard's Closing Soon track
    surfaces.

    Rather than waiting a full cycle, these run against the board the run just
    published. They take a plain list of Listings and are idempotent, so this is
    the same shape as fill_voter_phone.py and the other board maintenance
    scripts.

USAGE
    python3 scripts/catchup_failed_enrichers.py [--dry-run] [--only skip_trace]

    Refuses to run while the engine holds the board. One writer at a time.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402


def _engine_running() -> bool:
    # The pattern must not begin with "-": pgrep reads a leading dash as an
    # option, matches nothing, and the guard silently never fires.
    r = subprocess.run(
        ["pgrep", "-f", "--", r"run_local\.sh|-m foreclosure_scraper|merge_today_sources"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


async def _run_one(name: str, listings: list) -> dict:
    if name == "incarceration":
        from foreclosure_scraper.enrichment_incarceration import enrich_incarceration
        return await enrich_incarceration(listings) or {}
    if name == "jail_bookings":
        from foreclosure_scraper.enrichment_jail_bookings import enrich_jail_bookings
        return await enrich_jail_bookings(listings) or {}
    if name == "skip_trace":
        from foreclosure_scraper.enrichment_skip_trace import enrich_with_skip_trace
        await enrich_with_skip_trace(listings)
        return {}
    raise ValueError(f"unknown enricher {name!r}")


def _phones(listings) -> int:
    n = 0
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        st = raw.get("skip_trace")
        if (raw.get("owner_phone")
                or (isinstance(st, dict) and st.get("phone"))):
            n += 1
    return n


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", action="append",
                    choices=["incarceration", "jail_bookings", "skip_trace"],
                    help="run just these (default: all three)")
    args = ap.parse_args()

    if _engine_running():
        print("engine is running — refusing to touch the board", file=sys.stderr)
        return 1

    which = args.only or ["incarceration", "jail_bookings", "skip_trace"]
    listings = load_board()
    before_phones = _phones(listings)
    print(f"board: {len(listings):,} leads | with a phone before: {before_phones:,}")

    stats: dict[str, dict] = {}
    for name in which:
        print(f"\n--- {name}")
        try:
            stats[name] = await _run_one(name, listings)
            print(f"    {stats[name] or 'done'}")
        except Exception as exc:  # noqa: BLE001 - one enricher must not stop the rest
            print(f"    FAILED: {type(exc).__name__}: {str(exc)[:160]}")
            stats[name] = {"failed": f"{type(exc).__name__}"}

    after_phones = _phones(listings)
    print(f"\nwith a phone after: {after_phones:,}  (+{after_phones - before_phones:,})")

    if args.dry_run:
        print("dry run — board not written")
        return 0
    lp, _ = write_artifact(
        listings, {"notes": f"catch-up enrichers: {', '.join(which)}"})
    print(f"wrote {lp}: {len(listings):,} leads")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
