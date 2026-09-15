#!/usr/bin/env python3
"""Reconcile counties_sc.greenville_mie_adverts against the user-confirmed
scope policy (2026-09-15): "if they are actual foreclosures going to sale,
do not grab them. if they are real distressed etc then grab them."

The scraper was already landing 584 rows on the board (from an earlier
session), all blanket-typed FORECLOSURE_SALE. That fails _in_scope() for
Greenville outright (flip leads are denied there) -- verified 584/584
would be silently wiped by any real scope re-pass. Root cause: no per-row
distinction between an upcoming sale (a real "going to sale" lead) and a
sale whose advertised date has already passed (a resolved case whose
remaining value is the judgment-debt data -- a DISTRESSED signal, per the
user's own words). Fixed in greenville_mie_adverts.py's parse_advert().

This script REPLACES the source's existing board rows entirely with a
fresh fetch through the corrected type logic + the real _active_only()/
_in_scope() gates -- not an additive ingest. Scoped by source slug (safe:
touches only this source's own existing 584 rows, confirmed via the
source-scoped-dedupe pattern used throughout this session).

    python scripts/reconcile_greenville_mie_adverts.py --dry-run
    python scripts/reconcile_greenville_mie_adverts.py
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
from foreclosure_scraper.models import ListingType  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.greenville_mie_adverts import GreenvilleMIEAdverts  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120
SOURCE_SLUG = "counties_sc.greenville_mie_adverts"


async def _fetch_new() -> list:
    rows = list(await GreenvilleMIEAdverts().fetch())
    by_type = {}
    for r in rows:
        by_type[r.listing_type] = by_type.get(r.listing_type, 0) + 1
    print(f"  scraped={len(rows)} by_type={by_type}")
    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    kept_by_type = {}
    for r in kept:
        kept_by_type[r.listing_type] = kept_by_type.get(r.listing_type, 0) + 1
    print(f"  [OK]   {SOURCE_SLUG}: kept={len(kept)} kept_by_type={kept_by_type}")
    forecl_kept = [r for r in kept if r.listing_type == ListingType.FORECLOSURE_SALE]
    if forecl_kept:
        print(f"  WARNING: {len(forecl_kept)} FORECLOSURE_SALE rows passed "
              f"_in_scope() -- expected 0 for a Greenville-denied county; "
              f"double-check before landing.")
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping counties_sc.greenville_mie_adverts (772 adverts, slow)...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="greenville_mie_reconcile")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: li.source == SOURCE_SLUG
        target_rows_before = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from this source (being REPLACED): {len(target_rows_before):,}")

        # Replace, not merge: dedupe among the new rows only, so any old
        # row this fetch no longer confirms (a stale/removed advert, or one
        # that now correctly fails scope) does not survive.
        target_merged = dedupe(new_rows)
        merged = other_rows + target_merged
        print(f"board rows after: {len(merged):,} "
              f"(net change: {len(merged) - before:+,}, "
              f"source went {len(target_rows_before):,} -> {len(target_merged):,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"greenville_mie_reconcile": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
