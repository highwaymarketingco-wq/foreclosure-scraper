#!/usr/bin/env python3
"""Ingest Wake + Edgecombe County NC tax foreclosures after fixing both
scrapers' parsers (they were matching the wrong DOM shape entirely) and
seasonal gates (both wrongly went dormant every September-December) --
see wake_tax_foreclosure.py and edgecombe_tax_foreclosure.py's docstrings
for the full story. Both scrapers previously produced 0 board rows.

Verified live 2026-09-15: Wake has 4 real properties (one with a real
scheduled sale, Sept 9 2026); Edgecombe has 17, three with a sale
scheduled for THE NEXT DAY (Sept 16 2026) and one more Oct 14 2026.

Scoped dedupe by SOURCE (both currently at 0 existing board rows, so this
adds without touching any pre-existing board data) -- same pattern used
for ingest_nc_never_run_batch2.py after that script's county-scoped
dedupe surfaced an unrelated pre-existing dedupe risk.

    python scripts/ingest_wake_edgecombe_fixed.py --dry-run
    python scripts/ingest_wake_edgecombe_fixed.py
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
from foreclosure_scraper.scrapers.counties_nc.wake_tax_foreclosure import WakeTaxForeclosure  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.edgecombe_tax_foreclosure import EdgecombeTaxForeclosure  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

SOURCE_SLUGS = {"counties_nc.wake_tax_foreclosure", "counties_nc.edgecombe_tax_foreclosure"}


async def _fetch_new() -> list:
    wake, edgecombe = await asyncio.gather(WakeTaxForeclosure().fetch(), EdgecombeTaxForeclosure().fetch())
    wake, edgecombe = list(wake), list(edgecombe)
    print(f"  [OK]   counties_nc.wake_tax_foreclosure: {len(wake)} rows")
    print(f"  [OK]   counties_nc.edgecombe_tax_foreclosure: {len(edgecombe)} rows")
    return wake + edgecombe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows total")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="wake_edgecombe_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: li.source in SOURCE_SLUGS
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from these 2 sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"wake_edgecombe_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
