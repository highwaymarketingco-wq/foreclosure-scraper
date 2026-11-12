#!/usr/bin/env python3
"""Ingest 5 already-built, already-whitelisted NC scrapers that had never
actually landed a single board row despite working correctly.

FOUND 2026-09-15 via a background triage agent auditing all 31 NC scrapers
sitting at "zero board rows" in docs/SOURCE_REGISTER.md. All 5 of these
were already correctly registered in main.py's DATELESS_OK_SOURCES *and*
already had their raw-block keys allowlisted in web_artifact.py's
RAW_KEEP -- i.e. they were built to production standard and simply never
ran as part of any board-writing process. Verified live before ingesting:

    counties_nc.gaston_vacant             21,299 rows (Gaston, NC)
    counties_nc.lincoln_vacant            14,793 rows (Lincoln, NC)
    counties_nc.transylvania_vacant       11,105 rows (Transylvania, NC)
    counties_nc.transylvania_delinquent_tax  434 rows (Transylvania, NC)
    counties_nc.mcdowell_probate             414 rows (McDowell, NC)

ONE REAL BUG FIXED FIRST (see the same-day commit to gaston_vacant.py):
that scraper set Listing.sale_date from the county's SALEDATE field (the
CURRENT owner's last acquisition date, not a foreclosure auction date).
Every row therefore had a real, non-None sale_date more than 14 days in
the past, which main.py's _active_only() drops regardless of the
DATELESS_OK_SOURCES entry (that whitelist only applies when sale_date IS
None). Fixed to store SALEDATE in raw only, matching how the other 4
scrapers here already handle their own last-transaction-date fields
correctly. Verified live post-fix: 21,299/21,299 rows now pass
_active_only().

Scoped dedupe (existing rows in the 4 affected counties + new rows only,
spliced back into the untouched rest of the board) -- established pattern
this session for large single-batch ingests on an 8GB Mac.

    python scripts/ingest_nc_dateless_backlog.py --dry-run
    python scripts/ingest_nc_dateless_backlog.py
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
from foreclosure_scraper.scrapers.counties_nc.gaston_vacant import GastonVacant  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.lincoln_vacant import LincolnVacant  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.transylvania_vacant import TransylvaniaVacant  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax import TransylvaniaDelinquentTax  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.mcdowell_probate import McDowellProbate  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

COUNTIES = {"gaston", "lincoln", "transylvania", "mcdowell"}


async def _fetch_new() -> list:
    results = await asyncio.gather(
        GastonVacant().fetch(),
        LincolnVacant().fetch(),
        TransylvaniaVacant().fetch(),
        TransylvaniaDelinquentTax().fetch(),
        McDowellProbate().fetch(),
        return_exceptions=True,
    )
    out: list = []
    for name, res in zip(
        ("gaston_vacant", "lincoln_vacant", "transylvania_vacant",
         "transylvania_delinquent_tax", "mcdowell_probate"), results,
    ):
        if isinstance(res, BaseException):
            print(f"  [FAIL] {name}: {res!r}")
            continue
        rows = list(res)
        print(f"  [OK]   {name}: {len(rows):,} rows")
        out.extend(rows)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping 5 sources...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\nscraped: {len(new_rows):,} rows total")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="nc_dateless_backlog_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: (li.county or "").strip().lower() in COUNTIES and (li.state or "").upper() == "NC"
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows in {sorted(COUNTIES)}: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"nc_dateless_backlog_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
