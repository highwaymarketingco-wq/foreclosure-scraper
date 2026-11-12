#!/usr/bin/env python3
"""Ingest the Aiken Standard's foreclosure legal notices — Aiken's first-ever
lead source (a genuine zero-row county before this).

    python scripts/ingest_aiken_standard.py --dry-run
    python scripts/ingest_aiken_standard.py
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
from foreclosure_scraper.scrapers.newspapers.aiken_standard import AikenStandardForeclosures  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await AikenStandardForeclosures().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="aiken_standard_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_aiken = lambda li: (li.county or "").strip().lower() == "aiken" and (li.state or "").upper() == "SC"
        ai_rows = [li for li in rows if is_aiken(li)]
        other_rows = [li for li in rows if not is_aiken(li)]
        print(f"existing Aiken rows: {len(ai_rows):,}")

        ai_merged = dedupe(ai_rows + new_rows)
        merged = other_rows + ai_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"aiken_standard_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
