#!/usr/bin/env python3
"""Split the out-of-scope population off the board into its own preserved asset.

WHY. config.in_scope allows 18 counties and denies 42 (Charlotte, Raleigh,
Greenville SC, the whole NC/SC coast) - a deliberate footprint. main.py's
scope_repass deletes anything resolving outside it. Until the county backfill,
51,351 rows carried NO county, so scope_repass could not judge them and they
survived: the 94,384 board was really 37,909 in-footprint leads plus 51,351 that
were merely invisible to the filter.

Giving them counties made them judgeable, so the board's true in-footprint size
surfaced - and the count guard, whose high-water mark (94,384) was set while
those rows were still hidden, became mathematically unsatisfiable: max achievable
43,033 against a floor of 84,945. No full run can publish until that is resolved.

WHAT THIS DOES. Exports the out-of-scope rows to their own file FIRST, so the
board can legitimately shrink to its real footprint without losing anything.
It does NOT modify the board. Nothing is deleted.

The exported population is not junk:
  ~44,989  liensnc construction lien-agent filings - contractors and
           owner-investors, a genuine cash-buyer / skip-trace asset (89% carry
           contact details), simply not motivated sellers
  ~6,362   REAL distress outside the footprint (tax delinquent, lis pendens,
           demolition permits, judgments) - keep these; a footprint can change,
           and re-scraping them costs a full run.

    python scripts/split_out_of_scope.py --dry-run
    python scripts/split_out_of_scope.py
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"
OUT_DIR = REPO / "exports"

# liensnc is a construction-activity lane, not distress - segregate it so the
# genuine out-of-footprint distress is not buried under 45k contractor rows.
_CONSTRUCTION = ("liensnc",)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.config import in_scope

    src = DOCS / "listings.json.gz"
    with gzip.open(src, "rt", encoding="utf-8") as f:
        board = json.load(f)

    keep, construction, distress = [], [], []
    stats = collections.Counter()
    for rec in board:
        cty, st = rec.get("county"), rec.get("state")
        if not cty or in_scope(cty, st):
            keep.append(rec)
            stats["in_scope_or_countyless"] += 1
            continue
        s = str(rec.get("source") or "")
        if any(k in s for k in _CONSTRUCTION):
            construction.append(rec)
            stats["out_construction"] += 1
        else:
            distress.append(rec)
            stats["out_real_distress"] += 1

    print(f"board {len(board):,}")
    print(f"  stays on board (in-scope or countyless) : {stats['in_scope_or_countyless']:,}")
    print(f"  OUT - construction lien agent (liensnc) : {stats['out_construction']:,}")
    print(f"  OUT - real distress, wrong county       : {stats['out_real_distress']:,}")

    by_c = collections.Counter(
        f"{r.get('county')}, {r.get('state')}" for r in distress)
    print("\n  out-of-footprint DISTRESS by county (top 10):")
    for k, v in by_c.most_common(10):
        print(f"    {v:>5,}  {k}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    for name, rows in (("out_of_scope_construction", construction),
                       ("out_of_scope_distress", distress)):
        if not rows:
            continue
        p = OUT_DIR / f"{name}.json.gz"
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, default=str)
        print(f"  wrote {p}  ({len(rows):,} rows, {p.stat().st_size/1048576:.1f} MB)")

    print("\nThe board itself is UNCHANGED. Nothing was deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
