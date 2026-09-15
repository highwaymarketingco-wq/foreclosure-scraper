#!/usr/bin/env python3
"""Ingest Berkeley County SC's delinquent Real Property tax roll, pulled
directly from the paystar.io payment portal's own unauthenticated search
API (see counties_sc.berkeley_paystar_tax's docstring for the full story --
in short, its unified `/api/search` endpoint answers an EMPTY searchTerm
with facet filters, so the whole roll comes back with no name enumeration).

Scoped dedupe (existing Berkeley rows + new rows only, spliced back into the
untouched rest of the board) rather than a full-board dedupe() -- established
pattern this session for single-county ingests on an 8GB Mac.

    python scripts/ingest_berkeley_paystar_tax.py --dry-run
    python scripts/ingest_berkeley_paystar_tax.py
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
from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import BerkeleyPaystarTax  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


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

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="berkeley_paystar_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_berkeley = lambda li: (li.county or "").strip().lower() == "berkeley" and (li.state or "").upper() == "SC"
        berkeley_rows = [li for li in rows if is_berkeley(li)]
        other_rows = [li for li in rows if not is_berkeley(li)]
        print(f"existing Berkeley rows: {len(berkeley_rows):,}")

        berkeley_merged = dedupe(berkeley_rows + new_rows)
        merged = other_rows + berkeley_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"berkeley_paystar_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
