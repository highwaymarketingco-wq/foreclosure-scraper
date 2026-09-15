#!/usr/bin/env python3
"""Ingest national.sc_public_index -- Charleston County only.

Found live during the 2026-09-15 national.* zero-row audit follow-up (the
agent flagged this module as "possibly a redundant duplicate" of
counties_sc.sc_public_index without running it live to check -- it is NOT
redundant: counties_sc.sc_public_index covers only the 7 Upstate core
counties; this module's Charleston-specific fast path
(jcmsweb.charlestoncounty.org via curl-cffi, no WAF) is genuinely
different coverage).

Live-verified: 17,411 total Charleston Common Pleas cases, 9,464 distinct
real party names across the full alphabet (not a parsing artifact --
double-checked after the first few rows looked suspiciously truncated,
e.g. "A, A", which turned out to be real short/initial-only names, not a
bug), 1,509 from 2024+ after the scraper's own year filter.

This script calls the module's Charleston-only helper directly
(`_curl_search_county`) rather than the class's full `fetch()`, which
loops through all 45 other SC counties via slow, heavier nodriver
browser automation against an F5/Varnish WAF -- untested and unverified
today, deliberately deferred (same tier of effort as other WAF-heavy
sources this project has set aside). Sets county="Charleston" directly
(the class's own `_to_listings` always leaves county=None, which is why
SCOPE_BYPASS_SOURCES/DATELESS_OK_SOURCES entries were still added for
the source as a whole -- this script gets the more precise real-county
treatment instead).

    python scripts/ingest_sc_public_index_charleston.py --dry-run
    python scripts/ingest_sc_public_index_charleston.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.models import ListingType, PropertyKind, Listing  # noqa: E402
from foreclosure_scraper.scrapers.national.sc_public_index import _curl_search_county  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120
SOURCE_SLUG = "national.sc_public_index"
MIN_YEAR = 2024


def _to_listing(case: dict) -> Listing | None:
    case_num = case.get("case_number", "")
    if not case_num:
        return None
    m = re.match(r"(\d{4})CP", case_num)
    year = int(m.group(1)) if m else 0
    if year < MIN_YEAR:
        return None
    now = datetime.utcnow()
    return Listing(
        source=SOURCE_SLUG,
        source_url="https://jcmsweb.charlestoncounty.org/PublicIndex/",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Charleston",
        case_number=case_num,
        first_seen=now,
        last_seen=now,
        raw={"sc_public_index": {
            "name": case.get("name"),
            "role": case.get("role"),
            "date_filed": case.get("date_filed"),
            "status": case.get("status"),
            "date_disposed": case.get("date_disposed"),
            "court": "SC Common Pleas",
        }},
    )


async def _fetch_new() -> list:
    cases = await _curl_search_county("charleston")
    rows = [li for c in cases if (li := _to_listing(c))]
    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    print(f"  [OK]   {SOURCE_SLUG} (Charleston): raw_cases={len(cases)} "
          f"2024+={len(rows)} kept={len(kept)}")
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping national.sc_public_index (Charleston only)...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="sc_public_index_charleston_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: li.source == SOURCE_SLUG
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from this source: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"sc_public_index_charleston_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
