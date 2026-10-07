#!/usr/bin/env python3
"""Join the local parcel cache onto the board. Fills situs, owner mailing, value, sqft.

WHY THIS EXISTS AS A SCRIPT
    100 county caches were built holding 11.5M parcels, 10.8M of them carrying an owner
    MAILING address -- and the board's mailing coverage stayed at 65%, because
    enrich_gis_attrs only runs inside a full pipeline run and no run had landed since.
    The single biggest contact win available was sitting on disk, unused. SC owner
    contact is the measured binding constraint (Cherokee SC was at 1% mailing).

SAFETY
  * FILLS ONLY. Never overwrites a value the board already has, never adds or removes a
    row, and asserts the row count is unchanged.
  * The cache is keyed by county NAME with no state, so a lookup is only attempted when
    the county is not one of the four names that exist in BOTH Carolinas -- Beaufort,
    Cherokee, Lee, Union. Reading NC parcel data onto an SC lead would be worse than
    leaving the row empty.

    python scripts/join_parcel_cache_to_board.py --dry-run
    python scripts/join_parcel_cache_to_board.py
"""
from __future__ import annotations

import argparse
import re
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

#: This USED to hardcode {"beaufort","cherokee","lee","union"} and skip them
#: outright -- a second, independent copy of the same "cache key carries no
#: state" concern parcel_cache.DUAL_STATE_COUNTIES already solves, out of sync
#: with it (missing anson/chester) and, worse, now WRONG: lookup() has required
#: and correctly used an explicit state since 2026-09-13, and NC caches for Lee,
#: Cherokee, Union, Beaufort were built today. This blanket skip was silently
#: discarding real, correctly-resolvable NC data -- found 2026-09-14 when Lee/
#: Cherokee/Union/Beaufort NC rows all showed 0% value fill despite live
#: lookup(county, parcel_id, "NC") returning real market values for the same
#: parcel_ids. lookup() already refuses to guess when state is missing; this
#: file no longer needs its own copy of that rule, only a friendlier counter
#: for the one case lookup() can't explain on its own: no li.state at all.
from foreclosure_scraper.parcel_cache import DUAL_STATE_COUNTIES  # noqa: E402
from foreclosure_scraper.models import ListingType  # noqa: E402
_DUAL_LOWER = {n.lower() for n in DUAL_STATE_COUNTIES}
sys.path.insert(0, str(REPO / "scripts"))
from fill_address_from_parcel import classify_situs  # noqa: E402



_MAIL_STATE_RE = re.compile(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def _mail_state(mailing: str) -> str | None:
    """Two-letter state from the tail of a mailing string, e.g.
    '250 SAWGRASS CT SUMTER SC 29150' -> 'SC'. Returns None rather than guessing."""
    m = _MAIL_STATE_RE.search((mailing or "").strip().upper())
    return m.group(1) if m else None

def _fill_situs(li, hit, c) -> None:
    """The script's one extra rule on top of the shared join: write the cache situs only when
    it is a numbered street (2026-09-21: the cache "address" column is often NOT a street,
    e.g. "SPLIT FROM 116-00-01-048", "OFF SR 1151 EXT", "0 CALHOUN TRL"; see
    scripts/fill_address_from_parcel.py for the classifier and the city/zip rule)."""
    if hit.get("address") and not (li.street_address or "").strip():
        _sit = classify_situs(hit["address"])
        if _sit["kind"] == "numbered":
            li.street_address = _sit["address"]
            c["filled situs address"] += 1
        else:
            c[f"situs not written ({_sit['kind']})"] += 1


def apply_rows(rows, *, dry_run: bool = False) -> dict:
    """The join itself, on the rows load_board returned. Fill-only; never changes len(rows).
    Extracted 2026-09-21 so scripts/apply_board_fixes.py can run it in the same single load.

    Since 2026-10-07 the join lives in foreclosure_scraper.parcel_cache_join (one copy shared
    with enrich_gis_attrs, which now runs it over every row of a normal pipeline run); this
    adds the numbered-situs rule. Guards (overage rows, over-shared parcel ids, dual-state
    names with no state, owner_agrees False withholding the mailing) are unchanged."""
    from foreclosure_scraper.parcel_cache_join import join_listings
    return join_listings(rows, situs_fill=_fill_situs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="cache_join")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        c = apply_rows(rows, dry_run=args.dry_run)

        print()
        for k, n in c.most_common():
            print(f"  {n:>8,}  {k}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert len(rows) == before, "a join must never change the row count"
        write_artifact(rows, {
            "total": before,
            "notes": (f"parcel-cache join: {c['cache HIT']:,} hits, "
                      f"{c['filled owner mailing']:,} owner mailing, "
                      f"{c['filled situs address']:,} situs, {c['filled sqft']:,} sqft"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
