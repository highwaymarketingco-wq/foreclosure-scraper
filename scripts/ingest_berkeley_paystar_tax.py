#!/usr/bin/env python3
"""Ingest Berkeley County SC's delinquent Real Property tax roll, pulled
directly from the paystar.io payment portal's own unauthenticated search
API (see counties_sc.berkeley_paystar_tax's docstring for the full story --
in short, its unified `/api/search` endpoint answers an EMPTY searchTerm
with facet filters, so the whole roll comes back with no name enumeration).

REWRITTEN 2026-10-20: was load_board()/write_artifact() (full-board
materialization) -- that pattern thrashed 2+ hours on the Oracle VM's slow
disk without finishing on a similar-sized Johnston ingest tonight. Uses the
same streaming patch_existing_rows()/append_new_rows() pattern every other
backfill this session uses instead (confirmed: 8-15 min, under 500MB RSS).

    python scripts/ingest_berkeley_paystar_tax.py --dry-run
    python scripts/ingest_berkeley_paystar_tax.py
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
from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import BerkeleyPaystarTax  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)

_IS_BERKELEY = lambda rec_or_li: (
    str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "").strip().lower()
    == "berkeley"
    and str(rec_or_li.state if hasattr(rec_or_li, "state") else rec_or_li.get("state") or "").upper() == "SC"
)


async def _fetch_new() -> list:
    return list(await BerkeleyPaystarTax().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    mailing = sum(1 for r in new_rows if (r.raw.get("owner_mailing") or {}).get("mailing"))
    absentee = sum(1 for r in new_rows if (r.raw.get("owner_mailing") or {}).get("absentee"))
    out_of_state = sum(1 for r in new_rows if (r.raw.get("owner_mailing") or {}).get("out_of_state"))
    print(f"with mailing address: {mailing:,} | absentee: {absentee:,} | out-of-state: {out_of_state:,}")

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_BERKELEY(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"existing Berkeley SC dedupe_keys on board: {len(existing_keys):,}")

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

    print(f"\nclassified {len(new_rows):,} Berkeley tax-roll leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")

    if args.dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    with board_lock(REPO, owner="berkeley_paystar_ingest"):
        if patches:
            pstats = patch_existing_rows(patches, {"berkeley_paystar_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"berkeley_paystar_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
