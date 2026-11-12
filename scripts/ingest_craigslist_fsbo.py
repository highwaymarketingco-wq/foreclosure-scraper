#!/usr/bin/env python3
"""Ingest national.craigslist_fsbo -- regression fix from the 2026-09-15
national.* zero-row audit.

A memory record says this source previously worked with 264 confirmed real
leads; it had regressed to 0. Root cause found by the audit and confirmed
live: the scraper emits real, current FSBO listings (255 on this run, real
titles/prices/URLs/lat-lng) with `county=None` -- county is only ever meant
to be filled in later by geocode enrichment -- but `main._in_scope()` runs
on the RAW listing before that enrichment step, so every single fetch was
being wiped at the scope gate. Fixed by adding "national.craigslist_fsbo"
to SCOPE_BYPASS_SOURCES (same treatment already given to the CourtListener
bankruptcy/civil/adversary sources for the identical "county arrives late"
shape). Already correctly in DATELESS_OK_SOURCES.

These rows land as "state-only" (real lat/lng + price + URL, no derived
street_address/city/county -- Craigslist FSBO posts don't expose an exact
address, only an approximate map pin) -- the same accepted shape the
CourtListener bypass sources already use on this board today. A future
reverse-geocoder (e.g. FCC's free Census Block API, lat/lng -> county FIPS)
would upgrade these to full county-tagged leads; that's a new enrichment
module, not in scope for this landing.

    python scripts/ingest_craigslist_fsbo.py --dry-run
    python scripts/ingest_craigslist_fsbo.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.scrapers.national.craigslist_fsbo import CraigslistFSBO  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120
SOURCE_SLUG = "national.craigslist_fsbo"


async def _fetch_new() -> list:
    rows = list(await CraigslistFSBO().fetch())
    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    print(f"  [OK]   {SOURCE_SLUG}: scraped={len(rows)} kept={len(kept)}")
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping national.craigslist_fsbo...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="craigslist_fsbo_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: li.source == SOURCE_SLUG
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from this source: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"craigslist_fsbo_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
