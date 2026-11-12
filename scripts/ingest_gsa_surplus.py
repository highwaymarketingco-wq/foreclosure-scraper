#!/usr/bin/env python3
"""Ingest national.gsa_surplus -- rewritten 2026-09-15 (national.* zero-row
audit) to target the real GSA "assets identified for accelerated
disposition" page (the old URL this scraper used is a hard 404) with a real
selectolax parser anchored to each property card, instead of a loose regex.
Currently 1 in-footprint row (G. Ross Anderson Jr. Federal Building and
Courthouse, Anderson SC); a second SC property (Columbia) is correctly
rejected as outside the narrow flip footprint.

    python scripts/ingest_gsa_surplus.py --dry-run
    python scripts/ingest_gsa_surplus.py
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
from foreclosure_scraper.scrapers.national.gsa_surplus import GSASurplus  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120
SOURCE_SLUG = "national.gsa_surplus"


async def _fetch_new() -> list:
    rows = list(await GSASurplus().fetch())
    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    print(f"  [OK]   {SOURCE_SLUG}: scraped={len(rows)} kept={len(kept)}")
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping national.gsa_surplus...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="gsa_surplus_ingest")
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

        write_artifact(merged, {"gsa_surplus_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
