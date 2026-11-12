#!/usr/bin/env python3
"""Ingest newspapers.* scrapers found live but never run in the zero-row
audit (2026-09-15): newspapers.carolina_coast and newspapers.post_and_courier.
Both are already correctly whitelisted in DATELESS_OK_SOURCES (pre-auction
legal notices with no stated sale date) -- they were simply never actually
run by a real board-writing process. Small volume (1 row each as of this
run) but a genuine instance of the same "landed in code, never run" bug
pattern found repeatedly across NC/SC this session.

newspapers.hendersonville_lightning was also fixed this pass (FILE_RE now
matches 4-digit-year case numbers like "2016-SP-21"; ADDR_RE's lazy-group
greediness bug that truncated every address to its first letter is fixed)
but currently has 0 active notices (its 5 current notices are all stale
re-notices/tax-purchase-offer notices outside the active window) -- nothing
to ingest from it today, the fix just makes future runs correct.

Scoped dedupe by SOURCE SLUG (both sources confirmed at 0 existing board rows).

    python scripts/ingest_newspapers_never_run.py --dry-run
    python scripts/ingest_newspapers_never_run.py
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
from foreclosure_scraper.scrapers.newspapers.carolina_coast import CarolinaCoastForeclosures  # noqa: E402
from foreclosure_scraper.scrapers.newspapers.post_and_courier import PostAndCourierForeclosures  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120

SCRAPERS = [
    ("newspapers.carolina_coast", CarolinaCoastForeclosures),
    ("newspapers.post_and_courier", PostAndCourierForeclosures),
]
SOURCE_PREFIXES = tuple(slug for slug, _ in SCRAPERS)


async def _fetch_new() -> list:
    results = await asyncio.gather(*(cls().fetch() for _, cls in SCRAPERS), return_exceptions=True)
    out: list = []
    for (name, _cls), res in zip(SCRAPERS, results):
        if isinstance(res, BaseException):
            print(f"  [FAIL] {name}: {res!r}")
            continue
        rows = list(res)
        kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
        print(f"  [OK]   {name}: scraped={len(rows)} kept={len(kept)}")
        out.extend(kept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping 2 sources...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="newspapers_never_run_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: (li.source or "").startswith(SOURCE_PREFIXES)
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from these sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"newspapers_never_run_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
