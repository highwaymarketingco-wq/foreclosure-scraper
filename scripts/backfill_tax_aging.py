#!/usr/bin/env python3
"""Run enrichment_tax_owed over the published board to recover delinquent-tax YEAR.

Why this exists: tax delinquency is the primary lead filter for this business,
and the operative cut is "2-3 years behind" - one year is too early, the owner
still believes they will catch up. On the published board only 2.6% of the
90,414 tax-delinquent leads carry a usable year, so that filter can be applied
to almost nothing.

The three bugs that caused it (RAW_KEEP stripping source sub-dicts, the generic
scan self-matching raw['tax_owed'] from a prior run, and _SOURCES covering only
3 sources) were all FIXED in code on 2026-08-24 but only committed in the
2026-08-30 WIP snapshot - after the last successful board build on 2026-08-27.
So the fix has never actually run against the board. This runs it.

enrich_tax_owed is pure offline (no network). Fills only; never adds or removes
a row, so the count guard is untouched.

    python scripts/backfill_tax_aging.py --dry-run
    python scripts/backfill_tax_aging.py
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"
NOW_YEAR = 2026

_YEARISH = ("year", "tax_year", "first_cycle", "latest_cycle", "bill_year",
            "oldest_year", "bill_years", "tax_years", "year_span")


def _year_of(li) -> int | None:
    raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
    to = raw.get("tax_owed") or {}
    if not isinstance(to, dict):
        return None
    for k in _YEARISH:
        v = to.get(k)
        if isinstance(v, int) and 1990 < v <= NOW_YEAR:
            return v
        if isinstance(v, str):
            m = re.search(r"(19|20)\d{2}", v)
            if m:
                y = int(m.group(0))
                if 1990 < y <= NOW_YEAR:
                    return y
        if isinstance(v, list) and v:
            ys = [int(re.search(r"(19|20)\d{2}", str(x)).group(0))
                  for x in v if re.search(r"(19|20)\d{2}", str(x))]
            ys = [y for y in ys if 1990 < y <= NOW_YEAR]
            if ys:
                return min(ys)
    return None


def _stats(board, in_scope) -> dict:
    s = collections.Counter()
    for li in board:
        raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
        lt = str(getattr(li, "listing_type", "") or "").lower()
        if not ("tax" in lt or raw.get("tax_owed") or raw.get("two_year_delinquent")):
            continue
        s["tax"] += 1
        foot = bool(getattr(li, "county", None)) and in_scope(li.county, li.state)
        y = _year_of(li)
        if y:
            s["with_year"] += 1
            age = NOW_YEAR - y
            if foot and age >= 2:
                s["foot_2yr"] += 1
            if foot and age >= 3:
                s["foot_3yr"] += 1
        to = raw.get("tax_owed") or {}
        if isinstance(to, dict) and (to.get("amount") or to.get("balance")):
            s["with_amount"] += 1
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock
    from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
    from foreclosure_scraper.config import in_scope

    # board_lock takes the REPO ROOT, not docs/. Passing DOCS builds
    # docs/logs/.board.lock - a phantom lock that excludes nothing, so this
    # writer runs concurrently with the 4h-holding vision pass and its work is
    # silently reverted when that pass flushes its stale in-memory board.
    with board_lock(REPO):
        board = load_board(DOCS)
        before = _stats(board, in_scope)
        print(f"board {len(board):,} | tax-delinquent {before['tax']:,}")
        print(f"  BEFORE  year {before['with_year']:,} "
              f"({before['with_year']/max(before['tax'],1)*100:.1f}%)  "
              f"amount {before['with_amount']:,}  "
              f"| in-footprint 2yr+ {before['foot_2yr']:,}  3yr+ {before['foot_3yr']:,}")

        res = enrich_tax_owed(board)
        print(f"  enrich_tax_owed: {res}")

        after = _stats(board, in_scope)
        print(f"  AFTER   year {after['with_year']:,} "
              f"({after['with_year']/max(after['tax'],1)*100:.1f}%)  "
              f"amount {after['with_amount']:,}  "
              f"| in-footprint 2yr+ {after['foot_2yr']:,}  3yr+ {after['foot_3yr']:,}")
        print(f"\n  >>> year  +{after['with_year']-before['with_year']:,}")
        print(f"  >>> the operative filter (in-footprint, 2yr+): "
              f"{before['foot_2yr']:,} -> {after['foot_2yr']:,}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0

        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": (f"tax aging backfill: year {before['with_year']}->{after['with_year']}, "
                      f"in-footprint 2yr+ {before['foot_2yr']}->{after['foot_2yr']}"),
        }
        lp, _ = write_artifact(board, summary, docs_dir=DOCS)
        print(f"\nboard rows {len(board):,} (unchanged) | wrote {lp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
