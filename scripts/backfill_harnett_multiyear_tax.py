#!/usr/bin/env python3
"""One-time backfill: re-scrape Harnett County NC's own cama.harnett.org/ITSPublicHT
TaxBillSearch roll AT FULL DEPTH and land the result onto the already-published board.

WHY. Gap-matrix run 2026-10-21 (docs/gap_matrix/gap_list_2026-10-21.csv) flagged
multi_year_delinquent_tax for Harnett (4,221 applicable rows, built=no) with next_action "add a
tax-roll reader for tax/property card: cama.harnett.org" -- but that reader already exists and
is already wired into main.py (scrapers.counties_nc.nc_its_public_tax.PORTALS["Harnett"],
ITSPublicHT, full_model=True, since the 2026-10-09 top-80 build). enrichment_harnett_rollback_
exposure.py's own module docstring (2026-10-20) already flagged this exact gap as a RUN-DEPTH
problem, not a code gap: "a live probe of Harnett's current (2025) TaxBillSearch year alone
found 5,843 unpaid real-property bills (59 pages) -- every sampled board row currently carries
exactly ONE bill year, meaning the last production scrape of this county ran capped (self.limit,
back=1 year) rather than full (YEARS_BACK=20)". LIVE-RECONFIRMED 2026-10-21 (board_stream scan,
real board, no network): all 1,361 Harnett NC rows carrying raw['nc_its_public_tax'] have exactly
ONE year on file; 0 carry raw['multi_year_delinquent_tax'].

Same shape as last night's Granville fix (scripts/backfill_granville_multiyear_tax.py): the fix
is simply running the EXISTING, UNMODIFIED scrapers.counties_nc.nc_its_public_tax.NcItsPublicTax
scraper for this one county with no sample cap -- no new reader, no new parser.
NcItsPublicTax.aggregate() already folds every matched parcel's full per-year bill set into
raw['nc_its_public_tax'] AND, when a parcel clears the multi-year gate (>=2 distinct unpaid years,
>=1 matured), directly into raw['multi_year_delinquent_tax'] too (_canonical_multi_year) -- so a
fresh full-depth fetch's own Listing.raw already carries everything this backfill needs to write;
no separate restatement pass (enrichment_its_public_multiyear_tax.py) is required here.

NOT THE SAME GAP AS rollback_exposure (already built 2026-10-20,
enrichment_harnett_rollback_exposure.py) -- that module reads a DIFFERENT product on the same
host (BasicSearch/ViewParcel's "Deferred" Property-Values line) and does not depend on this
backfill or vice versa.

BOARD I/O: board_stream.iter_board_rows() once, then patch_existing_rows()/append_new_rows()
under board_lock(), same discipline as every backfill this session uses (never
load_board()/write_artifact() at this board's size). LOCK SCOPE: the lock wraps ONLY the final
write call, never the live fetch or the classify step -- the live fetch is pure network I/O and
holding the board lock across it blocks every other concurrent writer for however long the scrape
takes (this exact mistake cost hours elsewhere tonight). wait=600/poll=10 so a transient
collision with another writer queues briefly instead of discarding this run's results outright.

    python scripts/backfill_harnett_multiyear_tax.py --dry-run
    python scripts/backfill_harnett_multiyear_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("ITS_TAX_COUNTIES", "Harnett")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax import NcItsPublicTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)

_IS_HARNETT = lambda rec_or_li: (  # noqa: E731
    str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "").replace(
        " County", "").strip().lower() == "harnett"
    and str(rec_or_li.state if hasattr(rec_or_li, "state") else rec_or_li.get("state") or "").upper() == "NC")


async def _fetch_new() -> list:
    scraper = NcItsPublicTax()
    rows = list(await scraper.fetch())
    print(f"county_stats: {getattr(scraper, 'county_stats', {})}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"ITS_TAX_COUNTIES scope: {os.environ.get('ITS_TAX_COUNTIES')}")
    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} parcel-level leads (full depth)")
    if not new_rows:
        print("nothing scraped -- aborting.")
        return 1

    multi_year = sum(1 for r in new_rows if isinstance(r.raw, dict) and r.raw.get("multi_year_delinquent_tax"))
    years_seen = sorted({y for r in new_rows if isinstance(r.raw, dict)
                         for y in (r.raw.get("nc_its_public_tax") or {}).get("years") or []})
    print(f"with multi_year_delinquent_tax (>=2 distinct unpaid years, >=1 matured): {multi_year:,}")
    print(f"distinct tax years covered this fetch: {years_seen}")

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_HARNETT(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"\nexisting Harnett NC dedupe_keys on board: {len(existing_keys):,}")

    patches: dict[str, dict] = {}
    appends: list[Listing] = []
    seen_this_run: set[str] = set()
    for li in new_rows:
        key = li.dedupe_key()
        if key in seen_this_run:
            continue
        seen_this_run.add(key)
        if key in existing_keys:
            patches[key] = {"raw": li.raw}
        else:
            appends.append(li)

    print(f"\nclassified {len(new_rows):,} fresh Harnett tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")
    patch_multi_year = sum(1 for p in patches.values() if p["raw"].get("multi_year_delinquent_tax"))
    append_multi_year = sum(1 for li in appends if isinstance(li.raw, dict) and li.raw.get("multi_year_delinquent_tax"))
    print(f"\n  of the patches, multi_year_delinquent_tax qualifies: {patch_multi_year:,}")
    print(f"  of the appends, multi_year_delinquent_tax qualifies: {append_multi_year:,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="harnett_multiyear_tax_backfill", wait=600, poll=10):
        if patches:
            pstats = patch_existing_rows(patches, {"harnett_multiyear_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"harnett_multiyear_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
