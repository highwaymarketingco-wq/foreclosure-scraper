#!/usr/bin/env python3
"""Ingest Johnston County NC's delinquent-tax-file -> NC OneMap crosswalk producer
(counties_nc.johnston_delinquent_tax_crosswalk) into the live board.

Same pattern as scripts/ingest_greenville_delinquent_tax.py / ingest_dillon_delinquent_tax.py: a
dedupe_key collision here is EXPECTED and desirable -- a resolved parcel that already carries a
board row (all 8 of them, as of the 2026-10-20 crosswalk, are counties_nc.nc_heir_estate_parcels
estate-lead rows for the SAME PIN) is the same real property seen from a second angle (a heir/
estate owner-of-record signal AND a confirmed delinquent-tax balance) -- a corroboration this
engine already values, not a wrong-person hazard. So this script runs the real dedupe() pass
(same merge logic the full pipeline uses), scoped to Johnston County NC only -- a full-board
dedupe() over 400K+ rows is known to take minutes-to-hours on this hardware; every dedupe_key
this producer's rows can produce is Johnston-scoped (parcel:NC:johnston:... -- they always carry
a resolved parcel_id, never fall through to an address/case/url key), so deduping just [existing
Johnston rows + new rows] and splicing the result back in is equivalent to a full-board pass for
these rows, at a fraction of the cost.

    python scripts/ingest_johnston_tax_crosswalk.py --dry-run
    python scripts/ingest_johnston_tax_crosswalk.py
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
from foreclosure_scraper.scrapers.counties_nc.johnston_delinquent_tax_crosswalk import (  # noqa: E402
    JohnstonDelinquentTaxCrosswalk,
)
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

_IS_JOHNSTON = lambda li: (
    (li.county or "").strip().lower() == "johnston" and (li.state or "").upper() == "NC")


async def _fetch_new() -> list:
    s = JohnstonDelinquentTaxCrosswalk()
    rows = list(await s.safe_run())
    print(f"scraper outcome: {s.last_outcome}; run_stats: {s.run_stats}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows "
          f"({sum(1 for r in new_rows if r.parcel_id):,} with a resolved parcel)")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="johnston_tax_crosswalk_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        jo_rows = [li for li in rows if _IS_JOHNSTON(li)]
        other_rows = [li for li in rows if not _IS_JOHNSTON(li)]
        print(f"existing Johnston NC rows: {len(jo_rows):,} (scoped dedupe input, "
              f"vs {before:,} for a full-board pass)")

        jo_merged = dedupe(jo_rows + new_rows)
        merged = other_rows + jo_merged
        print(f"board rows after dedupe: {len(merged):,} "
              f"(net new: {len(merged) - before:,}; "
              f"{len(jo_rows) + len(new_rows) - len(jo_merged):,} merged into existing rows)")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"johnston_tax_crosswalk_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
