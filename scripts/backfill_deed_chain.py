#!/usr/bin/env python3
"""Run enrichment_deed_chain.enrich_deed_chain() board-wide.

100% offline, no network calls -- it only reorganizes deed/sale data other
enrichers already gathered (assessor_card.sales, county_sales, gis.last_sale,
rod_docs, relationship_signal) into a unified per-listing timeline. Worth
re-running now: today's parcel-resolution, gis_attrs_full, and comps
backfills all landed a lot of new gis.last_sale / sales data this function
has never seen. Fast (pure in-memory), no chunking needed.

    python scripts/backfill_deed_chain.py --dry-run
    python scripts/backfill_deed_chain.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_deed_chain")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("deed_chain"))
        print(f"rows with deed_chain before: {before:,}")

        if args.dry_run:
            print("\nDRY RUN — enrich_deed_chain() not called, nothing written.")
            return 0

        stats = enrich_deed_chain(rows)
        after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("deed_chain"))
        print(f"\nstats: {stats}")
        print(f"rows with deed_chain after: {after:,} (+{after - before:,})")

        write_artifact(rows, {"backfill_deed_chain": after - before}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
