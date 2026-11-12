#!/usr/bin/env python3
"""Ingest Dillon County SC's delinquent-tax list — Dillon's first-ever lead
source (a genuine zero-row county before this).

Dillon has zero existing board rows today, so in practice this run is a
pure append -- but it still runs through the same patch-vs-append
classification as every other ingest: a Dillon parcel appearing here and on
some future Dillon source would be the same real property/person, a
corroboration signal, not a wrong-person hazard (not a York-style
abort-on-collision case).

REWRITTEN 2026-10-21: was load_board()/write_artifact() (full-board
materialization) -- confirmed tonight that pattern does ~62GB of disk I/O
for this ~5GB/447K-row board and can run 2+ hours without finishing on this
project's hosts. Uses the same streaming patch_existing_rows()/
append_new_rows() pattern as scripts/ingest_berkeley_paystar_tax.py instead.

    python scripts/ingest_dillon_delinquent_tax.py --dry-run
    python scripts/ingest_dillon_delinquent_tax.py
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
from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import DillonDelinquentTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)

_IS_DILLON = lambda rec_or_li: (
    str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "").strip().lower()
    == "dillon"
    and str(rec_or_li.state if hasattr(rec_or_li, "state") else rec_or_li.get("state") or "").upper() == "SC"
)


async def _fetch_new() -> list:
    return list(await DillonDelinquentTax().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_DILLON(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"existing Dillon SC dedupe_keys on board: {len(existing_keys):,}")

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

    print(f"\nclassified {len(new_rows):,} Dillon tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")

    if args.dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    with board_lock(REPO, owner="dillon_tax_ingest"):
        if patches:
            pstats = patch_existing_rows(patches, {"dillon_delinquent_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"dillon_delinquent_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
