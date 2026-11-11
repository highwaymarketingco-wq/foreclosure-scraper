#!/usr/bin/env python3
"""Ingest Orangeburg County SC's real Register-of-Deeds adverse filings --
Federal tax liens + mechanic's liens -- from the newly-built, live-tested
orangeburg_scrod.py scraper (2026-11-11). See that module's docstring for why
this county was previously mis-sourced as a GovOS CountyFusion tenant.

Same streaming patch_existing_rows()/append_new_rows() pattern as
scripts/ingest_greenville_delinquent_tax.py -- never load_board() on this
multi-GB board. board_lock() is given a generous wait (not the 0.0 default)
because tonight's board has several other concurrent writers cycling the
lock every 15-20s; a 0-wait lock grab would almost certainly lose this run's
scraped data to a BoardLockBusy on first contention.

    python scripts/ingest_orangeburg_scrod.py --dry-run
    BOARD_APPEND_ALLOW_LARGE=1 python scripts/ingest_orangeburg_scrod.py

BOARD_APPEND_ALLOW_LARGE=1 is required for the real run (not the dry-run) once
the board passes append_new_rows()'s own 2400MB ceiling -- confirmed live
2026-11-11, board source measured at 5396MB. Left as a caller-supplied env var
rather than set in code, matching every other ingest/backfill script in this
project: the "supervised run" override is a decision for whoever launches it,
not a default baked into the script.
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
from foreclosure_scraper.scrapers.counties_sc.orangeburg_scrod import OrangeburgSCROD  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, append_new_rows, board_lock, patch_existing_rows,
)


def _is_orangeburg_sc(rec_or_li) -> bool:
    get = (lambda k: getattr(rec_or_li, k, None)) if hasattr(rec_or_li, "county") else rec_or_li.get
    return (str(get("county") or "").strip().lower() == "orangeburg"
            and str(get("state") or "").upper() == "SC")


async def _fetch_new() -> list[Listing]:
    return list(await OrangeburgSCROD().fetch())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows "
          f"({sum(1 for r in new_rows if r.plaintiff):,} mechanic liens, "
          f"{sum(1 for r in new_rows if not r.plaintiff):,} federal tax liens, "
          f"{sum(1 for r in new_rows if r.street_address):,} with a street address)")
    if not new_rows:
        print("nothing scraped -- aborting.")
        return 1

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _is_orangeburg_sc(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"existing Orangeburg SC dedupe_keys on board: {len(existing_keys):,}")

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

    print(f"\nclassified {len(new_rows):,} Orangeburg SC ROD leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="orangeburg_scrod_ingest", wait=3600, poll=10):
        if patches:
            pstats = patch_existing_rows(patches, {"orangeburg_scrod_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"orangeburg_scrod_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
