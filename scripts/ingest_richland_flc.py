#!/usr/bin/env python3
"""Ingest Richland County SC's FLC-owned-property list — Richland's first
real lead source beyond a single legal-notice hit.

Small (3 rows as of 2026-09-14) but scoped-dedupe is still the right call
(not a plain append): a future run could re-fetch the same 3 parcels and
this must not duplicate them.

    python scripts/ingest_richland_flc.py --dry-run
    python scripts/ingest_richland_flc.py
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
from foreclosure_scraper.scrapers.counties_sc.richland_flc import RichlandFLC  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await RichlandFLC().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="richland_flc_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_richland = lambda li: (li.county or "").strip().lower() == "richland" and (li.state or "").upper() == "SC"
        rc_rows = [li for li in rows if is_richland(li)]
        other_rows = [li for li in rows if not is_richland(li)]
        print(f"existing Richland rows: {len(rc_rows):,}")

        rc_merged = dedupe(rc_rows + new_rows)
        merged = other_rows + rc_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"richland_flc_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
