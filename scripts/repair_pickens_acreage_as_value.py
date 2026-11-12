#!/usr/bin/env python3
"""Clear ACREAGE that was stored in Pickens SC value columns.

Found 2026-09-20 while validating a new Pickens value layer against the board: the
board's Pickens `market_value` for 2,030 leads was under $1,000 (0.59, 1.24, 6.59 ...)
and matched the parcel's ACREAGE, not a price. parcel_cache.py once mapped
market_value to "CalcAcres" (an acreage field); the comment there records the fix
but the rows written before it were never repaired. The bad number also fed
assessed_value (the acreage rounded up: 1.0, 2.0, 7.0, on 1,410 rows), the computed
valuation, equity, the stack tier (one such lead was tiered HOT off a $0.59 "value")
and the rank. The parcel layer publishes no appraised value, so the honest value
is unknown, not small.

Rule (Pickens SC only): market_value is corrupt when 0 < market_value < 100, or when
0 < market_value < 1000 and it is within 30% (or 1.0) of the row's acreage or within
1.5 of a tiny assessed_value. Measured on the live board: 2,030 rows, and no tiny value
>= $100 that is not near the acreage, so nothing plausibly real is caught. Every other
county's tiny values are left alone: they bear no relation to acreage and look like
genuinely cheap land.

This clears the inputs only. Run scripts/recompute_valuation.py afterwards (from a
directory other than the repo root: its score_board call would otherwise parse the
1.1 GB docs/listings.json) so calc, equity, distress and rank are re-derived.

    python scripts/repair_pickens_acreage_as_value.py            # streams the board, counts only
    python scripts/repair_pickens_acreage_as_value.py --apply    # ONLY board process
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

TINY_ASSESSED = 1000.0     # a Pickens assessed/tax value under $1,000 is implausible


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def acreage_as_value(state, county, market_value, acreage, assessed_value) -> bool:
    """True when this Pickens SC row's market_value is really an acreage."""
    if (state or "").upper() != "SC" or (county or "").replace(" County", "").strip() != "Pickens":
        return False
    mv = _num(market_value)
    if mv is None or not (0 < mv < 1000):
        return False
    if mv < 100:
        return True
    ac = _num(acreage)
    av = _num(assessed_value)
    near_acreage = ac is not None and ac > 0 and abs(mv - ac) <= max(0.30 * ac, 1.0)
    near_assessed = av is not None and 0 < av < TINY_ASSESSED and abs(mv - av) <= 1.5
    return bool(near_acreage or near_assessed)


def plan_changes(market_value, assessed_value, tax_value) -> dict:
    """Which value columns to clear on a row already identified as corrupt."""
    out = {"market_value": True}
    av = _num(assessed_value)
    tv = _num(tax_value)
    out["assessed_value"] = av is not None and 0 < av < TINY_ASSESSED
    out["tax_value"] = tv is not None and 0 < tv < TINY_ASSESSED
    return out


def _dry_run() -> int:
    from foreclosure_scraper.board_stream import iter_board_rows
    by_src: Counter = Counter()
    cols: Counter = Counter()
    n = 0
    for r in iter_board_rows():
        if not acreage_as_value(r.get("state"), r.get("county"), r.get("market_value"),
                                r.get("acreage"), r.get("assessed_value")):
            continue
        n += 1
        by_src[str(r.get("source")).split(".")[-1]] += 1
        for col, do in plan_changes(r.get("market_value"), r.get("assessed_value"), r.get("tax_value")).items():
            cols[col] += bool(do)
    print(f"Pickens rows whose market_value is really an acreage: {n:,}")
    print("columns that would be cleared:", dict(cols))
    for s, c in by_src.most_common(6):
        print(f"  {c:6,}  {s}")
    print("\nDRY RUN, nothing written. Re-run with --apply, then run recompute_valuation.py.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run()

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    with board_lock(REPO, owner="repair_pickens_acreage_as_value"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        cleared: Counter = Counter()
        for li in rows:
            if not acreage_as_value(li.state, li.county, li.market_value, li.acreage, li.assessed_value):
                continue
            for col, do in plan_changes(li.market_value, li.assessed_value, li.tax_value).items():
                if do:
                    setattr(li, col, None)
                    cleared[col] += 1
        assert len(rows) == n
        print(f"board rows: {n:,}; cleared: {dict(cleared)}")
        write_artifact(rows, {"repair_pickens_acreage_as_value": dict(cleared)}, docs_dir=REPO / "docs")
        print(f"wrote board: {n:,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
