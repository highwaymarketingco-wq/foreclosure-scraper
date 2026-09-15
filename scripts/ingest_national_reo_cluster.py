#!/usr/bin/env python3
"""Ingest 3 national.* REO scrapers flagged by the 2026-09-15 zero-row audit
as "clears every known filter (_in_scope, _active_only, already in
DATELESS_OK_SOURCES) and still shows zero board rows" -- the agent could not
isolate a downstream defect in the time available.

Working hypothesis, tested here: these are not broken at all -- they were
simply never actually landed. The full orchestrated pipeline (main.py) is
the only thing that would normally reach national.* sources, and per
project memory it has been dead since late July (57h hang, OOM). Every
other zero-row source fixed this session turned out to be exactly this
"landed in code, never actually run" pattern once someone ran an ad-hoc
ingest against it. This script is that test for these three.

    national.usda_properties   -- 336 real SC properties, REO type
    national.hibid_real_estate -- 16 real auctions, REO/AUCTION type
    national.freddie_homesteps -- 30 real NC listings, REO type

    python scripts/ingest_national_reo_cluster.py --dry-run
    python scripts/ingest_national_reo_cluster.py
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
from foreclosure_scraper.scrapers.national.freddie_homesteps import FreddieHomeSteps  # noqa: E402
from foreclosure_scraper.scrapers.national.hibid_real_estate import HibidRealEstate  # noqa: E402
from foreclosure_scraper.scrapers.national.usda_properties import USDAProperties  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120

SCRAPERS = [
    ("national.usda_properties", USDAProperties),
    ("national.hibid_real_estate", HibidRealEstate),
    ("national.freddie_homesteps", FreddieHomeSteps),
]
SOURCE_PREFIXES = tuple(slug for slug, _ in SCRAPERS)


async def _fetch_new() -> list:
    out: list = []
    for name, cls in SCRAPERS:
        try:
            rows = list(await cls().fetch())
        except Exception as e:
            print(f"  [FAIL] {name}: {e!r}")
            continue
        kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
        print(f"  [OK]   {name}: scraped={len(rows)} kept={len(kept)}")
        out.extend(kept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping 3 sources...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="national_reo_cluster_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: (li.source or "") in SOURCE_PREFIXES
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from these sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"national_reo_cluster_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
