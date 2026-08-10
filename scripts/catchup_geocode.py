#!/usr/bin/env python3
"""Re-geocode the leads the main run's time budget left without coordinates.

WHY THIS EXISTS
    enrichment_geocode.enrich() runs under a WALL-CLOCK budget, GEOCODE_BUDGET_S,
    default 600s. That budget is not a bug: Nominatim sleeps ~1s per lead, so a
    few thousand address-less leads once stalled a full run for 8.5 hours. When
    the budget expires the remaining leads switch to fast_only, which skips the
    network tiers and takes an instant county-seat centroid.

    On the 2026-08-06 run that fired: `geocode.budget_hit`, and the run finished
    with 6,136 leads still carrying no lat/lng. Those leads are invisible on the
    map and cannot be scored on anything positional.

    This re-runs the SAME enricher against the published board with a budget
    large enough to finish, so the run stays fast and the slow tail happens
    afterwards instead of never.

WHAT IT CAN AND CANNOT RECOVER — read this before expecting 6,136
    Measured on the 2026-08-06 GIS checkpoint, of the 17,367 rows then lacking
    coordinates: 23.4% had a street address, 77.7% had a county, and 3,841 had
    NEITHER an address nor a county. That last group is not geocodable by any
    budget, because there is nothing to geocode. Re-running recovers the leads
    that ran out of clock, not the leads that ran out of data.

    For the address-less-but-parcelled leads the real fix is address resolution
    (parcel -> situs), not geocoding; that is enrichment_gis_attrs' job, and
    scripts/catchup_failed_enrichers.py is the sibling for the enrichers that
    die outright.

USAGE
    python3 scripts/catchup_geocode.py [--dry-run] [--budget-s 14400] [--limit N]

    Refuses to run while the engine holds the board. One writer at a time.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import os
import subprocess
import sys
import time
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


def _missing(listings):
    return [li for li in listings
            if getattr(li, "latitude", None) is None
            or getattr(li, "longitude", None) is None]


def _classify(listings) -> dict:
    """Split the no-geo pool by what it actually has to work with."""
    out = collections.Counter()
    for li in listings:
        has_addr = bool((getattr(li, "street_address", "") or "").strip())
        has_cty = bool((getattr(li, "county", "") or "").strip())
        if has_addr:
            out["has_address (fully geocodable)"] += 1
        elif has_cty:
            out["county only (centroid only)"] += 1
        else:
            out["no address, no county (UNGEOCODABLE)"] += 1
    return dict(out)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report the pool and exit without geocoding or writing")
    ap.add_argument("--budget-s", type=float, default=14400.0,
                    help="wall-clock budget in seconds (default 4h, vs the run's 600s)")
    ap.add_argument("--limit", type=int, default=0,
                    help="only attempt the first N missing leads (0 = all)")
    args = ap.parse_args()

    if _engine_running():
        print("engine is running and holds the board — refusing to write. "
              "Re-run after it publishes.")
        return 1

    listings = load_board()
    if not listings:
        print("no board found — nothing to do")
        return 1
    missing = _missing(listings)
    print(f"board: {len(listings):,} leads | without lat/lng: {len(missing):,}")
    for k, v in sorted(_classify(missing).items(), key=lambda x: -x[1]):
        print(f"   {v:6,}  {k}")
    if not missing:
        return 0
    if args.dry_run:
        print("\n--dry-run: stopping before geocode")
        return 0

    if args.limit:
        missing = missing[:args.limit]
    # The enricher reads its budget from the environment, so raise it here
    # rather than editing the module's default: the run's 600s is correct FOR
    # THE RUN, and this script exists precisely to pay the slow cost off-line.
    os.environ["GEOCODE_BUDGET_S"] = str(args.budget_s)
    from foreclosure_scraper.enrichment_geocode import enrich as enrich_geocode

    t0 = time.monotonic()
    print(f"\ngeocoding {len(missing):,} leads with a {args.budget_s:.0f}s budget "
          f"(the run uses 600s) ...")
    await enrich_geocode(missing)
    filled = sum(1 for li in missing
                 if li.latitude is not None and li.longitude is not None)
    still = len(missing) - filled
    print(f"filled {filled:,} | still missing {still:,} | "
          f"{time.monotonic() - t0:.0f}s")

    if not filled:
        print("nothing gained — not rewriting the board")
        return 0
    # load_board/write_artifact keep the vision/comps/cama sidecar intact; a
    # bare write_artifact on a freshly-built list wipes it.
    #
    # write_artifact() takes summary as a REQUIRED positional arg — omitting it
    # is a TypeError, and since it's the last statement in main(), that meant
    # this script did all its geocoding in memory and then crashed trying to
    # save it, discarding the whole pass. Caught 2026-08-10 when a live
    # catchup-chain run hit exactly this and exited 1 after filling coordinates
    # it then never persisted.
    summary = {"notes": f"catchup_geocode: filled {filled:,} of {len(missing):,} "
                        f"leads missing lat/lng"}
    write_artifact(listings, summary)
    total_missing = len(_missing(listings))
    print(f"board rewritten. leads without lat/lng now: {total_missing:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
