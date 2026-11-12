#!/usr/bin/env python3
"""One-time/repeatable backfill: run the REAL, unmodified UnionDelinquentTax scraper and land
its Union County NC real-estate tax-delinquency leads onto the already-published board.

WHY THIS EXISTS (2026-11-11, bot_wall_inhouse sweep). Tonight's gap_matrix run classified
multi_year_delinquent_tax/rollback_exposure/etc for Union, NC as a bot wall on
unioncountync.gov needing Playwright/stealth. Live-verified first (2026-11-11, bare curl,
realistic UA): the wall is REAL (HTTP 403, server: AkamaiGHost, on both the homepage and the
tax-foreclosure page) -- not a stale classification, unlike several siblings in the same sweep
(sc-charleston.publicaccessnow.com, rutherfordcountync.gov, taxaccess.leecountync.gov and
www.polknc.gov all answered a bare curl with a clean 200, no wall at all, live-checked the same
night). The bypass used is this project's OWN existing curl-cffi Chrome-impersonation tier
(`http_client.get_text(..., impersonate=True)`, documented in http_client.py's own module
docstring) -- no browser process, no new technique. Full reasoning, the live header evidence
and the CSV's real shape are in `scrapers/counties_nc/union_delinquent_tax.py`'s own docstring;
read that before changing this script.

This is a BRAND NEW source for a county that never had one -- unlike the Duplin/Granville/
Mecklenburg multi-year backfills this mirrors, there is no existing Union NC board population
to patch into; most fresh rows should land as genuinely new appends. The dedupe_key() check
against the existing board is still run (not skipped) in case another source already carries
one of these same parcels under a different signal -- merge into that row rather than
duplicate it.

Same lightweight patch_existing_rows()/append_new_rows() streaming pattern every backfill in
this project uses (never load_board()/write_artifact() at this board's size). The lock is held
ONLY around the final write -- the scrape above it is live network I/O against a just-bypassed
WAF with zero board-file interaction of its own, so holding the lock across it would starve
every sibling backfill for however long that fetch takes (the exact mistake this project's own
notes record being fixed elsewhere tonight, scripts/backfill_mecklenburg_tax.py).

    python scripts/backfill_union_delinquent_tax.py --dry-run
    python scripts/backfill_union_delinquent_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("FORECLOSURE_UNION_NC_TAX", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.union_delinquent_tax import UnionDelinquentTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)


def _is_union_nc(rec: dict) -> bool:
    county = str(rec.get("county") or "").replace(" County", "").strip().lower()
    state = str(rec.get("state") or "").upper()
    return county == "union" and state == "NC"


async def _fetch_new() -> list[Listing]:
    scraper = UnionDelinquentTax()
    return list(await scraper.fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} Union County NC real-estate tax-delinquency parcels")
    if not new_rows:
        print("nothing scraped (wall re-blocked, page shape changed, or doc link not found) "
              "-- aborting without touching the board.")
        return 1

    multi_year = sum(1 for r in new_rows
                      if isinstance(r.raw, dict) and r.raw.get("multi_year_delinquent_tax"))
    total_owed = sum(r.judgment_amount or 0.0 for r in new_rows)
    print(f"with multi_year_delinquent_tax (>=2 distinct unpaid years, >=1 matured): {multi_year:,}")
    print(f"combined amount owed across all scraped parcels: ${total_owed:,.2f}")

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _is_union_nc(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        try:
            existing_keys[li.dedupe_key()] = rec
        except Exception:  # noqa: BLE001 - a malformed existing row is simply not a merge target
            continue
    print(f"\nexisting Union County NC dedupe_keys already on board: {len(existing_keys):,}")

    patches: dict[str, dict] = {}
    appends: list[Listing] = []
    seen_this_run: set[str] = set()
    for li in new_rows:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if key in seen_this_run:
            continue
        seen_this_run.add(key)
        if key in existing_keys:
            patches[key] = {"raw": li.raw}
        else:
            appends.append(li)

    print(f"\nclassified {len(new_rows):,} fresh Union County NC tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="union_delinquent_tax_backfill", wait=3600, poll=10):
        if patches:
            pstats = patch_existing_rows(
                patches, {"union_delinquent_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(
                appends, {"union_delinquent_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
