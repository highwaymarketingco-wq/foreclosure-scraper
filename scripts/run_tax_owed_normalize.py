#!/usr/bin/env python3
"""Run the tax_owed normalization pass (enrichment_tax_owed.enrich_tax_owed)
against the live board and write it back.

Pure Python, no network — safe to run any time, not tied to any one
scraper's ingest. Found needed 2026-09-14 while ingesting Greenville's new
delinquent-tax source: raw.<source>.total_due was landing on the board, but
raw.tax_owed (the normalized field _SLIM_RAW actually ships to phones) is
only ever produced by this pass, and it hadn't run recently enough to cover
it — or, it turned out, most of the board's other tax-ish sources either
(24,741 rows stamped board-wide in one run, not just Greenville's ~2,300).

    python scripts/run_tax_owed_normalize.py --dry-run
    python scripts/run_tax_owed_normalize.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="tax_owed_normalize")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        stats = enrich_tax_owed(rows)
        print(stats)

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        if not stats.get("stamped") and not stats.get("cross_referenced"):
            print("\nnothing to do.")
            return 0

        assert len(rows) == before, "row count changed — refusing to write"
        write_artifact(rows, {"tax_owed_normalize": stats}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged, tax_owed stamped on {stats['stamped']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
