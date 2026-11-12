#!/usr/bin/env python3
"""Ingest Lincoln County NC open code violations after fixing the TLS
chain issue that was blocking this scraper entirely, plus a missing
RAW_KEEP entry that would have silently stripped its raw.lincoln_code
block (violations list, contacts) on write even once the TLS block was
lifted. See lincoln_code_violations.py's module docstring for the full
TLS story. Previously 0 board rows.

Verified live 2026-09-15: 63 real properties (66 open violation cases),
real addresses, owner names correctly split from contractor/LLC names.

Scoped dedupe by SOURCE (currently 0 existing board rows for this slug).

    python scripts/ingest_lincoln_code_violations.py --dry-run
    python scripts/ingest_lincoln_code_violations.py
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
from foreclosure_scraper.scrapers.counties_nc.lincoln_code_violations import LincolnCodeViolations  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

SLUG = "counties_nc.lincoln_code_violations"


async def _fetch_new() -> list:
    return list(await LincolnCodeViolations().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="lincoln_code_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: li.source == SLUG
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from this source: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"lincoln_code_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
