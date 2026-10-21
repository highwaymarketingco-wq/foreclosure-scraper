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
current owner are two different people by definition). A collision here
patches the existing row's raw data; it never aborts.

REWRITTEN 2026-10-21: was load_board()/write_artifact() (full-board
materialization) -- confirmed tonight that pattern does ~62GB of disk I/O
for this ~5GB/447K-row board and can run 2+ hours without finishing on this
project's hosts. Uses the same streaming patch_existing_rows()/
append_new_rows() pattern as scripts/ingest_berkeley_paystar_tax.py instead.

    python scripts/ingest_greenville_delinquent_tax.py --dry-run
    python scripts/ingest_greenville_delinquent_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.greenville_delinquent_tax import GreenvilleDelinquentTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)

_IS_GREENVILLE = lambda rec_or_li: (
    str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "").strip().lower()
    == "greenville"
    and str(rec_or_li.state if hasattr(rec_or_li, "state") else rec_or_li.get("state") or "").upper() == "SC"
)


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

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_GREENVILLE(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"existing Greenville SC dedupe_keys on board: {len(existing_keys):,}")

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

    print(f"\nclassified {len(new_rows):,} Greenville tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")

    if args.dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    with board_lock(REPO, owner="greenville_tax_ingest"):
        if patches:
            pstats = patch_existing_rows(patches, {"greenville_delinquent_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"greenville_delinquent_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
