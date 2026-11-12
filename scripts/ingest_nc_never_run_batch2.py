#!/usr/bin/env python3
"""Ingest 10 more already-built NC scrapers found sitting at zero board rows
by the same 2026-09-15 triage as ingest_nc_dateless_backlog.py, but handled
DIFFERENTLY: these are real event-dated (auction) sources, not standing-
condition ones.

WHY THIS SCRIPT APPLIES _active_only() ITSELF, UNLIKE THE BACKLOG SCRIPT
    Checked each scraper's live output before batching: most of what these
    10 sources scrape is HISTORICAL RECORD -- county pages that keep a
    running log of past sales (auction_status "Sale Closed-Property Sold",
    "Settled- Property Redeemed", sale dates from 2022-2025) alongside the
    handful of genuinely upcoming ones. That's correct scraper behavior
    (the page really does list both), but it means a plain scoped-dedupe-
    and-write (the pattern used for the 5 dateless sources in
    ingest_nc_dateless_backlog.py) would dump resolved, already-closed
    sales onto the board mislabeled as live leads. main.py's own
    _active_only() is exactly the filter meant to sort this out (drops
    terminal auction_status values and sale dates outside the grace/
    horizon window) -- normally applied by a full pipeline run, which these
    scrapers had apparently never actually been part of. Applied here by
    hand so this scoped ingest behaves the way a real pipeline run would.

    Live yield when filtered this way (2026-09-15): most of the 10 sources
    contribute 0 (all their live rows are historical/terminal); the real
    net-new comes from cleveland_tax_foreclosure and rutherford_foreclosure.
    Ingesting all 10 anyway (rather than dropping the 0-yield ones from the
    script) so this stays the complete, correct picture of what these
    sources are worth right now, and so a future re-run picks up anything
    that becomes current later without needing code changes.

    python scripts/ingest_nc_never_run_batch2.py --dry-run
    python scripts/ingest_nc_never_run_batch2.py
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
from foreclosure_scraper.main import _active_only  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.brunswick_legal_notices import BrunswickLegalNotices  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.buncombe_tax_foreclosure import BuncombeTaxForeclosure  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.cleveland_tax_foreclosure import ClevelandTaxForeclosure  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.gaston_tax_foreclosures import GastonTaxForeclosures  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.haywood_tax_foreclosures import HaywoodTaxForeclosures  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.henderson_tax import HendersonTaxForeclosure  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.mcdowell_tax_foreclosure import McDowellTaxForeclosure  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.new_hanover_foreclosures import NewHanoverForeclosures  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_coastal_tax_foreclosure import NCCoastalTaxForeclosure  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.rutherford_foreclosure import RutherfordForeclosure  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

SCRAPER_CLASSES = [
    BrunswickLegalNotices, BuncombeTaxForeclosure, ClevelandTaxForeclosure,
    GastonTaxForeclosures, HaywoodTaxForeclosures, HendersonTaxForeclosure,
    McDowellTaxForeclosure, NewHanoverForeclosures, NCCoastalTaxForeclosure,
    RutherfordForeclosure,
]

#: SCOPED BY SOURCE, NOT BY COUNTY -- deliberately, after a dry run of a
#: county-scoped version came back NET NEGATIVE (-50 to -51 rows) twice in a
#: row. Root cause traced to New Hanover specifically (12 GENUINELY DISTINCT
#: liensnc addresses -- Juno Dr + Sidbury Landing, a subdivision -- all
#: sharing one subdivision-PARENT tax parcel, fused into 1 row by dedupe()'s
#: Pass 1 exact-key bucketing, which runs BEFORE the house-number guard that
#: only protects Pass 2's fuzzy matching), but excluding just that county
#: only recovered 1 of the ~50 missing rows -- the rest is smaller, quieter
#: instances of the same class of pre-existing cross-source key collision
#: scattered across the other 10 counties, apparently never surfaced before
#: because this broad a scope had never been deduped in one pass.
#:
#: All 10 scrapers here show ZERO existing board rows for their OWN slugs
#: (confirmed before writing this script), so there is nothing of theirs to
#: merge against, and scoping to "rows from these 10 sources" costs nothing
#: real: it is empty today. This adds the 30 new rows without touching any
#: pre-existing board data at all, so whatever latent cross-source dedup
#: opportunities (or further poisoned-key risks) exist in these counties'
#: EXISTING rows are left exactly as they are -- neither fixed nor further
#: risked by this ingest. See docs/WEEKEND_LOOP_QUEUE.md's 2026-09-15 entry:
#: the underlying issue (Pass 1 has no poisoned-parcel-id guard, only Pass 2
#: does) is a real, separate, codebase-wide finding that deserves its own
#: dedicated investigation, not a fix folded into this ingest.
SOURCE_SLUGS = {
    "counties_nc.brunswick_legal_notices", "counties_nc.buncombe_tax_foreclosure",
    "counties_nc.cleveland_tax_foreclosure", "counties_nc.gaston_tax_foreclosures",
    "counties_nc.haywood_tax_foreclosures", "counties_nc.henderson_tax",
    "counties_nc.mcdowell_tax_foreclosure", "counties_nc.new_hanover_foreclosures",
    "counties_nc.nc_coastal_tax_foreclosure", "counties_nc.rutherford_foreclosure",
}

HORIZON_DAYS = 120  # matches RuntimeConfig.sale_horizon_days default (config.py)


async def _fetch_new() -> list:
    results = await asyncio.gather(*(c().fetch() for c in SCRAPER_CLASSES), return_exceptions=True)
    out: list = []
    for cls, res in zip(SCRAPER_CLASSES, results):
        inst = cls()
        if isinstance(res, BaseException):
            print(f"  [FAIL] {inst.slug}: {res!r}")
            continue
        rows = list(res)
        kept = [r for r in rows if _active_only(r, HORIZON_DAYS)]
        print(f"  [OK]   {inst.slug}: scraped={len(rows)} active_now={len(kept)}")
        out.extend(kept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"scraping 10 sources (horizon={HORIZON_DAYS}d)...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal active-now rows across all 10: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="nc_batch2_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: li.source in SOURCE_SLUGS
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from these 10 sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"nc_batch2_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
