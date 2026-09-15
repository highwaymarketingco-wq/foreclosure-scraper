#!/usr/bin/env python3
"""Ingest Dillon County SC's delinquent-tax list — Dillon's first-ever lead
source (a genuine zero-row county before this).

Dillon has zero existing board rows, so this is a pure append with a
scoped-dedupe safety net (matching the pattern established for Greenville/
Richland) rather than a York-style abort-on-collision -- a Dillon parcel
appearing here and on some future Dillon source would be the same real
property/person, a corroboration signal, not a wrong-person hazard.

    python scripts/ingest_dillon_delinquent_tax.py --dry-run
    python scripts/ingest_dillon_delinquent_tax.py
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
from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import DillonDelinquentTax  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await DillonDelinquentTax().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="dillon_tax_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_dillon = lambda li: (li.county or "").strip().lower() == "dillon" and (li.state or "").upper() == "SC"
        dl_rows = [li for li in rows if is_dillon(li)]
        other_rows = [li for li in rows if not is_dillon(li)]
        print(f"existing Dillon rows: {len(dl_rows):,}")

        dl_merged = dedupe(dl_rows + new_rows)
        merged = other_rows + dl_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"dillon_tax_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
