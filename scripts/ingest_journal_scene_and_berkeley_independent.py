#!/usr/bin/env python3
"""Ingest the Journal Scene (Dorchester) and Berkeley Independent (Berkeley)
foreclosure legal notices — both counties previously stuck at 0-2 rows
despite post_and_courier.py's own docstring naming them as intended
coverage (it only ever queried one generic section that excludes them).

    python scripts/ingest_journal_scene_and_berkeley_independent.py --dry-run
    python scripts/ingest_journal_scene_and_berkeley_independent.py
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
from foreclosure_scraper.scrapers.newspapers.journal_scene import JournalSceneForeclosures  # noqa: E402
from foreclosure_scraper.scrapers.newspapers.berkeley_independent import BerkeleyIndependentForeclosures  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    js = list(await JournalSceneForeclosures().fetch())
    bi = list(await BerkeleyIndependentForeclosures().fetch())
    return js + bi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows total")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="dorchester_berkeley_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        counties = {"dorchester", "berkeley"}
        is_target = lambda li: (li.county or "").strip().lower() in counties and (li.state or "").upper() == "SC"
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing Dorchester+Berkeley rows: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"journal_scene_berkeley_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
