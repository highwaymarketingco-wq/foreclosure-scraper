#!/usr/bin/env python3
"""Ingest two law_firms scrapers found live but never run in the zero-row
audit (2026-09-15):

    law_firms.zacchaeus  -- 139 rows (47 future / 92 past sale dates),
                             TAX_SALE type; already correctly wired, simply
                             never run.
    law_firms.finkel     -- SC PDF parser; intermittently 403'd by the host
                             (finkellaw.com / finkellawcharleston.com), lands
                             opportunistically when it returns data. Landed
                             4 real rows on first live check.

Both sources have ZERO existing board rows, so dedupe is scoped by SOURCE
SLUG (not county), per the New Hanover/liensnc lesson earlier this session.

law_firms.alaw was live-verified too (26 rows, correctly parsed "Current
Sale Date" column) but every single row's sale date is >1yr stale
(max 2025-09-23) -- the firm's embedded SharePoint workbook is abandoned,
not a code bug -- so it is deliberately NOT ingested here (would net 0 rows
through _active_only() anyway). See docs/WEEKEND_LOOP_QUEUE.md.

Applies the REAL pipeline filters (main._in_scope, main._active_only)
rather than re-deriving them.

    python scripts/ingest_lawfirms_zacchaeus_finkel.py --dry-run
    python scripts/ingest_lawfirms_zacchaeus_finkel.py
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
from foreclosure_scraper.scrapers.law_firms.finkel import Finkel  # noqa: E402
from foreclosure_scraper.scrapers.law_firms.zacchaeus import Zacchaeus  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120

SCRAPERS = [
    ("law_firms.zacchaeus", Zacchaeus),
    ("law_firms.finkel", Finkel),
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

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="lawfirms_zacchaeus_finkel_ingest")
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

        write_artifact(merged, {"lawfirms_zacchaeus_finkel_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
