#!/usr/bin/env python3
"""Run enrichment_property_category.enrich_property_category() board-wide.

Not wired into main.py (confirmed via grep). 100% offline classification
into one of foreclosure/preforeclosure/tax_delinquency/distressed_property,
written to raw['property_category'] -- actively read by dashboard.js (the
colored category badge on every card, and its filter logic), so a low
coverage rate here is a real, user-visible dashboard gap, not just an
internal data-completeness stat. Confirmed 18.1% (31,844/175,518) before
this run.

    python scripts/backfill_property_category.py --dry-run
    python scripts/backfill_property_category.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_property_category import enrich_property_category  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_property_category")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("property_category"))
        print(f"property_category before: {before:,} ({100*before/len(rows):.1f}%)")

        if args.dry_run:
            print("\nDRY RUN — enrich_property_category() not called, nothing written.")
            return 0

        stats = enrich_property_category(rows)
        after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("property_category"))
        print(f"\nstats: {stats}")
        print(f"property_category after: {after:,} ({100*after/len(rows):.1f}%)  (+{after - before:,})")

        write_artifact(rows, {"backfill_property_category": stats}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
