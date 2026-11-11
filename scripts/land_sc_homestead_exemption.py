#!/usr/bin/env python3
"""One-time landing: run the two brand-new SC homestead-exemption scrapers --
counties_sc.york_homestead.YorkHomestead and counties_sc.lexington_homestead.LexingtonHomestead
(committed 9f6a80e, already deployed byte-identical to the VM, auto-discovered by
scrapers/_registry.py but never once run against the live board) -- and append their results
onto the board via the SAME narrow path scripts/land_york_jail_bookings.py already established
for "land one genuinely-new source's rows without running the full ~286-scraper main.py
pipeline": append_new_rows() (web_artifact.py), the real internal function main.py's own full
run() ultimately calls write_artifact() for, re-shaped to stream the existing board once and
skip the load_board()-materializes-everything / dedupe(fresh+prior) / full enrichment stack a
real main.py run would otherwise need just to land two new sources.

Both sources are property-keyed (parcel_id-based dedupe_key(), SC Code 12-37-250 elderly/
disabled/blind homestead exemption -- York ~80,600 parcels, Lexington ~28,300) and have never
written a single row to the board before, so append_new_rows()'s additive-only dedupe --
dedupe.py's _strong_sigs() + dedupe_key() + verification.core.row_keys(), the EXACT signatures
dedupe() itself uses, just streamed row-by-row instead of materialized -- is checked against the
WHOLE existing board for every candidate row; there is no prior-run old-dedupe-key-scheme
collision risk the way land_york_jail_bookings.py's docstring flagged for its other 8
pre-existing counties.

Both scrapers measured fast live (48.3s / 14.9s) -- board_lock() below wraps ONLY the final
append_new_rows() write, never the two fetch() calls above it. The existing board is over
BOARD_APPEND_MAX_SOURCE_MB's ceiling on both Mac and VM as of 2026-11-11 (board_append_size_
state() reports this up front) -- expected, not a bug -- so a real run needs --allow-large
(BOARD_APPEND_ALLOW_LARGE=1) exactly like the vacant-structure/vision patch scripts need
--allow-large for the patch-side ceiling.

    python scripts/land_sc_homestead_exemption.py --dry-run
    python scripts/land_sc_homestead_exemption.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.lexington_homestead import (  # noqa: E402
    LexingtonHomestead,
)
from foreclosure_scraper.scrapers.counties_sc.york_homestead import YorkHomestead  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_append_size_state, board_lock,
)

_IDENTITY_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                    "case_number", "source_url", "listing_type")


def _new_scrapers():
    # Fresh instances each call -- safe_run() mutates per-instance state
    # (last_outcome/last_reason/partial), so a retry must not reuse a dirty one.
    return [YorkHomestead(), LexingtonHomestead()]


async def _fetch_all(scrapers) -> list[Listing]:
    results = await asyncio.gather(*(s.safe_run() for s in scrapers))
    listings: list[Listing] = []
    for s, rows in zip(scrapers, results):
        print(f"  {s.slug}: {len(rows)} rows "
              f"(outcome={getattr(s, 'last_outcome', '?')!r} "
              f"reason={getattr(s, 'last_reason', '')!r})")
        listings.extend(rows)
    return listings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true",
                    help="set BOARD_APPEND_ALLOW_LARGE=1 for this run")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_append_size_state(docs_dir)
        print(f"board_append_size_state: {size_state}")
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    scrapers = _new_scrapers()
    print(f"fetching {', '.join(s.slug for s in scrapers)} ...")
    listings = asyncio.run(_fetch_all(scrapers))
    print(f"fetched {len(listings)} total candidate rows")
    if not listings:
        print("nothing to land.")
        return 0

    print("streaming existing board for a dedupe_key() preview "
          "(informational only -- append_new_rows() below does the real, full-signature "
          "additive-only dedupe against the live board at write time)...")
    existing_keys: set[str] = set()
    existing_total = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        existing_total += 1
        light = Listing.model_construct(**{k: rec.get(k) for k in _IDENTITY_FIELDS})
        try:
            existing_keys.add(light.dedupe_key())
        except Exception:  # noqa: BLE001
            continue
    print(f"existing board rows streamed: {existing_total}")

    new_listings: list[Listing] = []
    seen: set[str] = set()
    by_source: dict[str, int] = {}
    for li in listings:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        new_listings.append(li)
        by_source[li.source] = by_source.get(li.source, 0) + 1

    print(f"genuinely new (not already on board, dedupe_key() preview): "
          f"{len(new_listings)} of {len(listings)}")
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  {src}: {n}")

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for li in new_listings[:3]:
            print(" ", li.county, li.parcel_id, li.street_address, li.owner_name)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_sc_homestead_exemption", wait=3600, poll=10):
        stats = append_new_rows(
            new_listings,
            {"by_source": {s.slug: by_source.get(s.slug, 0) for s in scrapers}},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
