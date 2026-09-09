#!/usr/bin/env python3
"""Repair county values that scripts/backfill_liensnc_raw.py mis-derived.

LiensNC filers sometimes type the STATE into the county line, so the detail page
literally reads "NC County" / "North Carolina County". The re-parse extracted that
verbatim, giving 5,226 rows a county of "Nc" or "North Carolina". Those are not
counties, so main.py's scope_repass judged them off-footprint and dropped them —
even though many are Candler / Leicester / Asheville, i.e. Buncombe, squarely
INSIDE the 18-county footprint.

Fix, in order:
  1. county is a state name/abbrev  -> re-derive from city via upstate_county_for
  2. still unresolved              -> clear it, so the row is countyless again
                                      (scope_repass cannot judge a countyless row,
                                      which is how these behaved before the re-parse)

Fills/repairs only. Never adds or removes a row, so the count guard is untouched.

    python scripts/fix_liensnc_bogus_county.py --dry-run
    python scripts/fix_liensnc_bogus_county.py
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"

# A "county" that is really a state. Compared case-insensitively.
STATE_NOT_COUNTY = {
    "nc", "n.c.", "north carolina", "sc", "s.c.", "south carolina",
    "none", "n/a", "na", "unknown", "united states", "usa",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock
    from foreclosure_scraper._upstate_city_to_county import upstate_county_for
    from foreclosure_scraper.config import in_scope

    # board_lock takes the REPO ROOT, not docs/. Passing DOCS builds
    # docs/logs/.board.lock - a phantom lock that excludes nothing, so this
    # writer runs concurrently with the 4h-holding vision pass and its work is
    # silently reverted when that pass flushes its stale in-memory board.
    with board_lock(REPO):
        board = load_board(DOCS)
        st = collections.Counter()
        recovered = collections.Counter()

        for li in board:
            c = (getattr(li, "county", None) or "").strip()
            if not c or c.lower() not in STATE_NOT_COUNTY:
                continue
            st["bogus_found"] += 1
            city = (getattr(li, "city", None) or "").strip()
            state = (getattr(li, "state", None) or "").strip()
            fixed = upstate_county_for(city, state) if city else None
            if fixed:
                li.county = fixed
                st["repaired"] += 1
                if in_scope(fixed, state):
                    st["repaired_IN_footprint"] += 1
                    recovered[fixed] += 1
            else:
                li.county = None
                st["cleared"] += 1

        print(f"board {len(board):,}")
        print(f"  bogus state-as-county found : {st['bogus_found']:,}")
        print(f"  repaired via city lookup    : {st['repaired']:,}")
        print(f"     ...of which IN footprint : {st['repaired_IN_footprint']:,}  <- recovered leads")
        print(f"  cleared to countyless       : {st['cleared']:,}")
        if recovered:
            print("\n  recovered into these footprint counties:")
            for k, v in recovered.most_common(10):
                print(f"     {v:>5,}  {k}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0

        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": (f"liensnc county repair: {st['repaired']} re-derived "
                      f"({st['repaired_IN_footprint']} in-footprint), "
                      f"{st['cleared']} cleared"),
        }
        lp, _ = write_artifact(board, summary, docs_dir=DOCS)
        print(f"\nboard rows {len(board):,} (unchanged) | wrote {lp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
