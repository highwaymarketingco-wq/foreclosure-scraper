#!/usr/bin/env python3
"""Quarantine parcel_id values that are not parcel identifiers.

`scripts/scrape_liensnc.py` extracts the parcel with

    PIN_RE = re.compile(r'(?:pin|tms|parcel|tax\\s*map)\\s*#?\\s*:?\\s*([\\w\\-]+)',
                        re.IGNORECASE)

There is no word boundary before ``pin`` and the pattern is case-insensitive, so
the letters "pin" match INSIDE ordinary words:

    "Pinehurst"    -> parcel_id 'ehurst'   (127 board rows, 122 distinct properties)
    "Pineville"    -> parcel_id 'eville'   (140 rows, 130 distinct properties)
    "PIN number:"  -> parcel_id 'number'   (250 rows, 247 distinct properties)
    also nacle / ewood / eview / ecrest / dale / ecliff / yon / lot / pin

`dedupe._strong_sigs` then emits ``("p", parcel_id, state)`` for any parcel of 4+
characters, so every property on a "Pine*" street in the state shares one
signature and the union-merge fuses them into a single row. Measured on the live
94,384-row board: 977 rows carry a pure-alpha parcel_id and 903 of them would be
wrongly collapsed. That is only ~4% of the merge's 22,115 collapses (the rest are
genuine duplicates of the same property from different sources) -- but it is 903
real properties silently deleted, and it also poisons every parcel-keyed join to
assessor / CAMA data.

This script does NOT edit scrape_liensnc.py -- that file is the operator's and is
not touched without their say-so. It repairs the DATA already on the board:

  * moves the bogus value to ``raw['parcel_id_rejected']`` so nothing is lost and
    the decision stays auditable,
  * nulls ``parcel_id`` so the row stops emitting a false parcel signature.

A row keeps every other field, including its address signatures, so genuine
duplicates of it still merge correctly. Nothing is removed from the board.

Run with --dry-run first.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_lock_dir, load_board, write_artifact,
)

# A real NC/SC parcel identifier contains at least one digit. Pure alpha is the
# PIN_RE bug. Also catch the bare label words the regex leaves behind.
_ALPHA_ONLY = re.compile(r"^[A-Za-z]{3,}$")
_LABEL_WORDS = {"number", "pin", "lot", "id", "no", "num", "tms", "parcel",
                "map", "block", "unit", "none", "n/a", "na", "tbd"}


def is_fake_parcel(pid: str | None) -> bool:
    if not pid:
        return False
    s = pid.strip()
    if not s:
        return False
    if s.lower() in _LABEL_WORDS:
        return True
    # No digit anywhere -> not a parcel identifier in either state.
    return bool(_ALPHA_ONLY.match(s)) and not any(c.isdigit() for c in s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    print(f"board lock dir: {board_lock_dir(REPO)}")
    # board_lock(REPO), never board_lock(DOCS): passing the docs dir creates a
    # phantom lock at docs/logs/.board.lock that excludes nothing, which is how a
    # concurrent vision job silently reverted an earlier repair.
    with board_lock(REPO):
        listings = load_board(REPO / "docs")
        before = len(listings)
        print(f"board rows: {before:,}")

        touched = 0
        by_value: Counter[str] = Counter()
        by_source: Counter[str] = Counter()
        samples = []
        for li in listings:
            pid = li.parcel_id
            if not is_fake_parcel(pid):
                continue
            touched += 1
            by_value[str(pid).lower()] += 1
            by_source[li.source or "?"] += 1
            if len(samples) < 8:
                samples.append((pid, li.street_address, li.city, li.county, li.source))
            if not args.dry_run:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["parcel_id_rejected"] = pid
                li.raw["parcel_id_rejected_reason"] = "PIN_RE matched 'pin' inside a word"
                li.parcel_id = None

        print(f"\nrows with a NON-parcel parcel_id: {touched:,}")
        print("\n--- by bogus value ---")
        for v, n in by_value.most_common(15):
            print(f"  {n:>6,}  {v!r}")
        print("\n--- by source ---")
        for v, n in by_source.most_common(8):
            print(f"  {n:>6,}  {v}")
        print("\n--- samples ---")
        for pid, addr, city, cty, src in samples:
            print(f"  pid={pid!r:12} {str(addr)[:34]:<34} {str(city)[:16]:<16} {cty} [{src}]")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        if not touched:
            print("\nnothing to repair.")
            return 0

        assert len(listings) == before, "repair must not change the row count"
        write_artifact(listings, {
            "total": len(listings),
            "notes": (f"repair_fake_parcel_ids: quarantined {touched:,} non-parcel "
                      f"parcel_id values (PIN_RE matched 'pin' inside a word); "
                      f"rows unchanged at {before:,}"),
            # No rows were removed, so the guard needs no allowance here.
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows, {touched:,} parcel_ids quarantined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
