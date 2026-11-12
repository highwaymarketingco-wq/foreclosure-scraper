#!/usr/bin/env python3
"""One-time backfill: re-scrape Granville County NC's own tax.granvillecounty.org/ITSPublic
TaxBillSearch roll AT FULL DEPTH and land the result onto the already-published board.

WHY. Live board scan 2026-10-21 found all 882 Granville rows carrying raw['nc_its_public_tax']
have exactly ONE bill year on file (a capped/sample read, not the scraper's own full
YEARS_BACK=20 default) -- a scraper RUN-DEPTH gap, the same shape
enrichment_harnett_rollback_exposure.py's docstring already documented for Harnett. Live-probed
the real portal the same day: 2025/2024/2023/2020 all answer real unpaid bills (one real
multi-year parcel found in the first 20 rows alone: account 1117983 / parcel 089610454922,
delinquent both 2024 and 2025), so the fix is simply running the EXISTING, UNMODIFIED
scrapers.counties_nc.nc_its_public_tax.NcItsPublicTax scraper for this one county with no sample
cap -- no new reader, no new parser.

NcItsPublicTax.aggregate() already folds every matched parcel's full per-year bill set into
raw['nc_its_public_tax'] AND, when a parcel clears the multi-year gate (>=2 distinct unpaid years,
>=1 matured), directly into raw['multi_year_delinquent_tax'] too (_canonical_multi_year) -- so a
fresh full-depth fetch's own Listing.raw already carries everything this backfill needs to write;
no separate restatement pass (enrichment_its_public_multiyear_tax.py) is required here.

REWRITTEN to the lightweight patch_existing_rows()/append_new_rows() streaming pattern every
backfill this session uses (never load_board()/write_artifact() at this board's size), same
classify-into-patch-or-append shape as scripts/ingest_berkeley_paystar_tax.py's 2026-10-20
rewrite: a fresh scrape's Listing.dedupe_key() either matches an existing Granville board row
(merge the fuller raw onto it -- patch_existing_rows() MERGES a raw update into the existing raw,
never replaces it, so grade/calc/skip_trace/etc on that row are untouched) or is a genuinely new
parcel this county's capped run never reached (append).

    python scripts/backfill_granville_multiyear_tax.py --dry-run
    python scripts/backfill_granville_multiyear_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("ITS_TAX_COUNTIES", "Granville")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax import NcItsPublicTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)

_IS_GRANVILLE = lambda rec_or_li: (  # noqa: E731
    str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "").replace(
        " County", "").strip().lower() == "granville"
    and str(rec_or_li.state if hasattr(rec_or_li, "state") else rec_or_li.get("state") or "").upper() == "NC"
)


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
        if not _IS_GRANVILLE(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"\nexisting Granville NC dedupe_keys on board: {len(existing_keys):,}")

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

    print(f"\nclassified {len(new_rows):,} fresh Granville tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")
    patch_multi_year = sum(1 for p in patches.values() if p["raw"].get("multi_year_delinquent_tax"))
    append_multi_year = sum(1 for li in appends if isinstance(li.raw, dict) and li.raw.get("multi_year_delinquent_tax"))
    print(f"\n  of the patches, multi_year_delinquent_tax qualifies: {patch_multi_year:,}")
    print(f"  of the appends, multi_year_delinquent_tax qualifies: {append_multi_year:,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="granville_multiyear_tax_backfill"):
        if patches:
            pstats = patch_existing_rows(patches, {"granville_multiyear_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"granville_multiyear_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
