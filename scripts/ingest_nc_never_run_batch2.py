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
from foreclosure_scraper.web_artifact import append_new_rows, board_lock  # noqa: E402

SCRAPER_CLASSES = [
    BrunswickLegalNotices, BuncombeTaxForeclosure, ClevelandTaxForeclosure,
    GastonTaxForeclosures, HaywoodTaxForeclosures, HendersonTaxForeclosure,
    McDowellTaxForeclosure, NewHanoverForeclosures, NCCoastalTaxForeclosure,
    RutherfordForeclosure,
]

#: REWRITTEN 2026-11-23 (found never having been run at all -- its own load_board()
#: call crashes outright now that the board is 5.7GB, same BoardLoadTooLarge family as
#: daily_api_refresh.py's confirmed 19GB OOM kill). Was: load_board() the WHOLE board,
#: filter to these 10 sources' existing rows (SOURCE_SLUGS, below) to dodge a real
#: NET-NEGATIVE cross-source dedupe collision (New Hanover's 12 distinct liensnc
#: addresses sharing one subdivision-parent tax parcel, fused by dedupe()'s Pass 1
#: exact-key bucketing), then write_artifact() the WHOLE board back. Now:
#: append_new_rows() streams the existing board ONCE (never materializes it), and its
#: dedupe check is additive-only BY CONSTRUCTION -- a candidate matching an existing
#: row is skipped, the existing row is never touched -- so the exact net-negative
#: failure mode above (an existing row getting fused/lost) cannot happen here at all,
#: not just avoided by scoping. SOURCE_SLUGS no longer filters anything (nothing to
#: filter now that load_board() is gone) -- kept as the expected-slugs sanity check in
#: main() below, so a scraper's slug drifting silently out of this set is caught.
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
    unexpected = {li.source for li in new_rows} - SOURCE_SLUGS
    assert not unexpected, f"scraper slug drifted out of SOURCE_SLUGS: {unexpected}"

    self_deduped = dedupe(new_rows)
    print(f"self-deduped (within this batch): {len(new_rows):,} -> {len(self_deduped):,}")

    if args.dry_run:
        print("\nDRY RUN — nothing written (append_new_rows() would stream-check these "
              "against the existing board and skip any already present).")
        return 0

    with board_lock(REPO, owner="nc_batch2_ingest", wait=1800, poll=10):
        stats = append_new_rows(self_deduped, {"nc_batch2_ingest": len(self_deduped)},
                                docs_dir=REPO / "docs")
    print(f"\n{stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
