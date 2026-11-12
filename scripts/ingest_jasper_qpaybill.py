#!/usr/bin/env python3
"""Ingest Jasper County SC's delinquent-tax roll, found 2026-09-15 on the
SAME qPayBill vendor the other 27 counties already use -- just under a
subdomain (jaspercountydelinquenttax) this scraper's roster never probed,
because Jasper's own site links a separate current-year payment portal on a
completely different vendor (paystar.io) as its primary "Pay Taxes" button.
See QPAYBILL_SUBS's "Jasper" entry for the full story.

Scoped dedupe (existing Jasper rows + new rows only, spliced back into the
untouched rest of the board) rather than a full-board dedupe() -- established
pattern this session for single-county ingests on an 8GB Mac.

    python scripts/ingest_jasper_qpaybill.py --dry-run
    python scripts/ingest_jasper_qpaybill.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ["QPAYBILL_ROLL_COUNTIES"] = "Jasper"

from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (  # noqa: E402
    QPayBillDelinquentRoll,
)
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await QPayBillDelinquentRoll().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="jasper_qpaybill_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_jasper = lambda li: (li.county or "").strip().lower() == "jasper" and (li.state or "").upper() == "SC"
        jasper_rows = [li for li in rows if is_jasper(li)]
        other_rows = [li for li in rows if not is_jasper(li)]
        print(f"existing Jasper rows: {len(jasper_rows):,}")

        jasper_merged = dedupe(jasper_rows + new_rows)
        merged = other_rows + jasper_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"jasper_qpaybill_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
