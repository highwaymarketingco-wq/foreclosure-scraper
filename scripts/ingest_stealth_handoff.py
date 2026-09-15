#!/usr/bin/env python3
"""Ingest national.stealth_handoff -- the Mac->VM cloud-split hand-off file.

Found and fixed 2026-09-15 (national.* zero-row audit): stealth_handoff.py's
own path resolution had an off-by-one (`Path(__file__).resolve().parents[3]`,
which lands on `src/` -- one level too shallow -- instead of the repo root at
`parents[4]`), so it always looked for `src/docs/handoff/stealth_leads.json`
(never existed) and silently returned [] on every run. The real file at
docs/handoff/stealth_leads.json holds 7,270 real leads pushed by the Mac's
residential-IP stealth scrapers (sc_public_index, ecourts, land.com sites,
zillow_foreclosures, law-firm sites, etc across 64 distinct source slugs).
It's 14 days stale (generated_at 2026-09-01) but stale stealth leads beat
none, per the scraper's own design ("we still ingest a stale file").

Each lead round-trips as a pre-formed Listing.model_validate(d), so it keeps
its ORIGINAL source slug -- not "national.stealth_handoff". Because those 64
source slugs (sc_public_index, nc_ecourts_lis_pendens, etc.) already carry
real existing board rows, this dedupe is scoped by the UNION of every source
slug actually present in the hand-off file (not the whole board, and not
"assume 0 existing" like the smaller single-source ingests this session) --
the correct generalization of the source-scoped-dedupe pattern established
earlier today.

    python scripts/ingest_stealth_handoff.py --dry-run
    python scripts/ingest_stealth_handoff.py
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
from foreclosure_scraper.scrapers.national.stealth_handoff import StealthHandoffScraper  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120


async def _fetch_new() -> list:
    rows = list(await StealthHandoffScraper().fetch())
    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    print(f"  [OK]   national.stealth_handoff: scraped={len(rows)} kept={len(kept)}")
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("reading stealth hand-off file...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    touched_sources = {r.source for r in new_rows}
    print(f"touches {len(touched_sources)} distinct existing source slugs")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="stealth_handoff_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: (li.source or "") in touched_sources
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows across those {len(touched_sources)} sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"stealth_handoff_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
