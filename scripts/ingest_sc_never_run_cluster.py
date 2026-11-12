#!/usr/bin/env python3
"""Ingest 7 SC scrapers found by the same 2026-09-15 zero-row-scraper audit
that covered NC earlier the same day, all confirmed to already work live
but never actually land board rows:

    counties_sc.sc_ust_registry        -- missing DATELESS_OK_SOURCES entry (fixed)
    counties_sc.zombie_properties      -- missing DATELESS_OK_SOURCES entry (fixed)
    counties_sc.sc_des_brownfields     -- was emitting garbage (fixed) + missing entry (fixed)
    counties_sc.sc_probate_notices     -- per-paper dynamic slug never matched the
                                           whitelisted base slug (fixed: prefix match
                                           in main._active_only)
    counties_sc.pickens_tax_sale       -- already correctly wired; simply never run
    counties_sc.terry_howe_auctions    -- already correctly wired; simply never run
                                           (AUCTION type -- a FLIP lead, so THIS
                                           ingest applies the real _in_scope() check,
                                           which restricts it to the 18-county
                                           footprint, same as a real pipeline run
                                           would)
    counties_sc.florence_delinquent_tax -- blocked by the stale 18-county-only
                                           scope gate (fixed 2026-09-15, confirmed
                                           directly with the user: distressed-type
                                           leads are in-scope anywhere in NC/SC)

Applies the REAL pipeline filters (main._in_scope, main._active_only)
rather than re-deriving them, so this landing matches exactly what a real
full pipeline run would keep.

Scoped dedupe by SOURCE (all 7 confirmed at 0 existing board rows).

    python scripts/ingest_sc_never_run_cluster.py --dry-run
    python scripts/ingest_sc_never_run_cluster.py
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
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.sc_ust_registry import SCUstRegistry  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.zombie_properties import ZombieProperties  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.sc_des_brownfields import SCDESBrownfields  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.sc_probate_notices import SCProbateNotices  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.pickens_tax_sale import PickensTaxSale  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.terry_howe_auctions import TerryHoweAuctions  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax import FlorenceDelinquentTax  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120

SCRAPERS = [
    ("counties_sc.sc_ust_registry", SCUstRegistry),
    ("counties_sc.zombie_properties", ZombieProperties),
    ("counties_sc.sc_des_brownfields", SCDESBrownfields),
    ("counties_sc.sc_probate_notices", SCProbateNotices),
    ("counties_sc.pickens_tax_sale", PickensTaxSale),
    ("counties_sc.terry_howe_auctions", TerryHoweAuctions),
    ("counties_sc.florence_delinquent_tax", FlorenceDelinquentTax),
]
# sc_probate_notices ships each row under a per-paper sub-slug
# ("counties_sc.sc_probate_notices.laurenscountyadvertiser", etc.), not the
# bare base slug -- match on prefix for the scope filter below.
SOURCE_PREFIXES = tuple(slug for slug, _ in SCRAPERS)


async def _fetch_new() -> list:
    results = await asyncio.gather(*(cls().fetch() for _, cls in SCRAPERS), return_exceptions=True)
    out: list = []
    for (name, _cls), res in zip(SCRAPERS, results):
        if isinstance(res, BaseException):
            print(f"  [FAIL] {name}: {res!r}")
            continue
        rows = list(res)
        kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
        print(f"  [OK]   {name}: scraped={len(rows)} kept={len(kept)}")
        out.extend(kept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping 7 sources...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows across all 7: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="sc_never_run_cluster_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: (li.source or "").startswith(SOURCE_PREFIXES)
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from these 7 sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"sc_never_run_cluster_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
