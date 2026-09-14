#!/usr/bin/env python3
"""Ingest Greenville County SC's delinquent tax sale roster — SC's largest
county by population, previously only 584 board rows.

Unlike the York overage-claim ingest, a dedupe_key collision here is
EXPECTED and desirable: a Greenville parcel already on the board (from
greenville_mie_adverts or greenville_hard_distress) that also shows up
delinquent on THIS list is the same real property/person seen from a second
angle (an active foreclosure lawsuit AND unpaid property tax) — a
corroboration signal this engine already values, not a wrong-person hazard
(contrast York's TAX_SALE_OVERAGE, where the claimant and the parcel's
current owner are two different people by definition). So this script runs
the real dedupe() pass — same merge logic the full pipeline uses — rather
than aborting on collision.

    python scripts/ingest_greenville_delinquent_tax.py --dry-run
    python scripts/ingest_greenville_delinquent_tax.py
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
from foreclosure_scraper.scrapers.counties_sc.greenville_delinquent_tax import GreenvilleDelinquentTax  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


async def _fetch_new() -> list:
    return list(await GreenvilleDelinquentTax().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows "
          f"({sum(1 for r in new_rows if r.parcel_id):,} with parcel, "
          f"{sum(1 for r in new_rows if not r.parcel_id):,} personal property)")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="greenville_tax_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        # Scoped dedupe, not a full-board dedupe(): a fresh timing test showed
        # dedupe() over the full ~130K-row board hadn't finished after 2m49s
        # of 100% CPU (this is an 8GB Mac; the codebase's own history notes
        # multi-hour full-board dedupe hangs). Safe to scope: every dedupe_key
        # these new rows can produce is Greenville-scoped (parcel:...:
        # greenville:... or case:...:greenville:...; none carry a zip_code,
        # so pass 2's cross-county zip-blocking branch can't reach them
        # either) -- so deduping [existing Greenville rows + new rows] and
        # splicing the result back in is identical to a full-board dedupe()
        # for these rows, at a fraction of the cost.
        is_greenville = lambda li: (li.county or "").strip().lower() == "greenville" and (li.state or "").upper() == "SC"
        gv_rows = [li for li in rows if is_greenville(li)]
        other_rows = [li for li in rows if not is_greenville(li)]
        print(f"existing Greenville rows: {len(gv_rows):,} (scoped dedupe input, "
              f"vs {before:,} for a full-board pass)")

        gv_merged = dedupe(gv_rows + new_rows)
        merged = other_rows + gv_merged
        print(f"board rows after dedupe: {len(merged):,} "
              f"(net new: {len(merged) - before:,}; "
              f"{len(gv_rows) + len(new_rows) - len(gv_merged):,} merged into existing rows)")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"greenville_delinquent_tax_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
