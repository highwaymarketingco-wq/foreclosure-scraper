#!/usr/bin/env python3
"""Ingest York County SC's Overage Claim List — York's first-ever lead source.

York was a zero-row county (its only prior entry, york_delinquent_tax, is
gated to Oct-Jan and returned nothing off-season). This runs the new
counties_sc.york_overage_claims scraper and appends its listings to the
board directly, bypassing the full pipeline run (unnecessary here: the
scraper already resolves situs from the local parcel cache itself, and the
full run's enrichers are explicitly guarded OFF for this listing_type — see
york_overage_claims.py's module docstring).

SAFETY: refuses to write if any new row's dedupe_key collides with an
existing board row (would trigger Listing.merge() and could blend two
different real-world facts about the same parcel into one row — see the
same module docstring). Verified 2026-09-14: zero pre-existing York rows on
the board, so this is expected to be a no-collision, pure-append run.

    python scripts/ingest_york_overage_claims.py --dry-run
    python scripts/ingest_york_overage_claims.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.scrapers.counties_sc.york_overage_claims import YorkOverageClaims  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await YorkOverageClaims().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} claimant rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="york_overage_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        existing_keys = {li.dedupe_key() for li in rows}
        new_keys = [li.dedupe_key() for li in new_rows]
        collisions = [k for k in new_keys if k in existing_keys]
        if collisions:
            print(f"\nABORT: {len(collisions)} new row(s) collide with an existing "
                  f"board dedupe_key — merging would blend two different real-world "
                  f"facts about the same parcel:")
            for k in collisions[:10]:
                print(f"    {k}")
            return 1
        dup_within_new = len(new_keys) - len(set(new_keys))
        if dup_within_new:
            print(f"\nNOTE: {dup_within_new} duplicate dedupe_key(s) within the new "
                  f"batch itself (same parcel, multiple claims across tax-sale years) "
                  f"— all kept as distinct rows since dedupe_key doesn't disambiguate "
                  f"by claim; York's list has no case where this happens today.")

        combined = rows + new_rows
        print(f"board rows after: {len(combined):,} (+{len(new_rows):,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert len(combined) == before + len(new_rows), "row count math is wrong — refusing to write"
        write_artifact(combined, {"york_overage_claims_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(combined):,} rows ({before:,} + {len(new_rows):,} new)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
