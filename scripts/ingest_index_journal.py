#!/usr/bin/env python3
"""Ingest the Index-Journal (Greenwood, SC) after fixing the glued-county-
name bug in the shared TownNews parser -- this scraper already existed and
was already running, but every row it ever produced had its county
silently nulled by validation.py before reaching the board (see
_townnews._resolve_county's docstring for the root cause).

    python scripts/ingest_index_journal.py --dry-run
    python scripts/ingest_index_journal.py
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
from foreclosure_scraper.scrapers.newspapers.index_journal import IndexJournalForeclosures  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await IndexJournalForeclosures().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="index_journal_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_gw = lambda li: (li.county or "").strip().lower() == "greenwood" and (li.state or "").upper() == "SC"
        gw_rows = [li for li in rows if is_gw(li)]
        other_rows = [li for li in rows if not is_gw(li)]
        print(f"existing Greenwood rows: {len(gw_rows):,}")

        gw_merged = dedupe(gw_rows + new_rows)
        merged = other_rows + gw_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"index_journal_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
