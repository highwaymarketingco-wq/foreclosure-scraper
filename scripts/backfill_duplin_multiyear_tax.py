#!/usr/bin/env python3
"""One-time backfill: re-scrape Duplin County NC's own www.bttaxpayerportal.com/ITSPublicDL
TaxBillSearch roll AT FULL DEPTH and land the result onto the already-published board.

WHY. enrichment_its_public_multiyear_tax.py (committed 2026-10-18, wired into main.py, and run
once as a backfill 2026-10-19 -- scripts/backfill_multiyear_tax_restatement.py, commit 530d8d89)
is a pure, no-network restatement of raw['nc_its_public_tax']['bills'] into the shared
raw['multi_year_delinquent_tax'] contract. It is NOT missing and NOT broken. Re-running that
exact backfill in --dry-run mode 2026-10-21 found it currently qualifies ZERO Duplin rows (and,
for that matter, zero rows for EVERY county on all three sibling vendor families -- qpaybill,
ptscloud, its_public -- 49,191 candidates streamed board-wide, 100% insufficient_history, 0
qualified). Live board scan the same day: 2,902 of 3,519 Duplin rows carry raw['nc_its_public_tax'],
but EVERY ONE sampled has exactly ONE bill year on file -- a scraper RUN-DEPTH gap, the identical
shape enrichment_granville_rollback_exposure.py's own docstring already documented for Granville
and backfill_granville_multiyear_tax.py already fixed for that county (board-wide: Granville/
Catawba/Iredell DO carry a handful of multi-year rows now; Duplin currently has none).

The scraper's own YEARS_BACK already defaults to 20 (ITS_TAX_YEARS_BACK env, unset tonight) --
scrapers.counties_nc.nc_its_public_tax.py separately documents a run-wide wall-clock deadline that
ROTATES the start county across its 12 PORTALS tenants (commit 92450fce), so a shared, multi-
county run can hit its deadline before any single county (especially one later in rotation) ever
gets its own FULL per-parcel year sweep landed -- not a Duplin-specific wall, a shared-budget
side effect. Running the EXISTING, UNMODIFIED NcItsPublicTax scraper scoped to ONLY Duplin
(ITS_TAX_COUNTIES=Duplin) removes that rotation/budget contention for this one county -- no new
reader, no new parser.

NcItsPublicTax.aggregate() already folds every matched parcel's full per-year bill set into
raw['nc_its_public_tax'] AND, when a parcel clears the multi-year gate (>=2 distinct unpaid years,
>=1 matured), directly into raw['multi_year_delinquent_tax'] too (_canonical_multi_year) -- so a
fresh full-depth fetch's own Listing.raw already carries everything this backfill needs to write;
no separate restatement pass (enrichment_its_public_multiyear_tax.py) is required here.

Same lightweight patch_existing_rows()/append_new_rows() streaming pattern every backfill this
session uses (never load_board()/write_artifact() at this board's size), same classify-into-
patch-or-append shape as scripts/backfill_granville_multiyear_tax.py: a fresh scrape's
Listing.dedupe_key() either matches an existing Duplin board row (merge the fuller raw onto it --
patch_existing_rows() MERGES a raw update into the existing raw, never replaces it, so grade/calc/
skip_trace/etc on that row are untouched) or is a genuinely new parcel the prior capped run never
reached (append).

    python scripts/backfill_duplin_multiyear_tax.py --dry-run
    python scripts/backfill_duplin_multiyear_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("ITS_TAX_COUNTIES", "Duplin")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax import NcItsPublicTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)

_IS_DUPLIN = lambda rec_or_li: (  # noqa: E731
    str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "").replace(
        " County", "").strip().lower() == "duplin"
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
        if not _IS_DUPLIN(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"\nexisting Duplin NC dedupe_keys on board: {len(existing_keys):,}")

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

    print(f"\nclassified {len(new_rows):,} fresh Duplin tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")
    patch_multi_year = sum(1 for p in patches.values() if p["raw"].get("multi_year_delinquent_tax"))
    append_multi_year = sum(1 for li in appends if isinstance(li.raw, dict) and li.raw.get("multi_year_delinquent_tax"))
    print(f"\n  of the patches, multi_year_delinquent_tax qualifies: {patch_multi_year:,}")
    print(f"  of the appends, multi_year_delinquent_tax qualifies: {append_multi_year:,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="duplin_multiyear_tax_backfill", wait=600, poll=10):
        if patches:
            pstats = patch_existing_rows(patches, {"duplin_multiyear_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"duplin_multiyear_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
