#!/usr/bin/env python3
"""Clear 'no divorce' stamps written by the old enricher during slow-portal rounds.

Found 2026-09-20: before ed15f11 (2026-09-18 12:16 EDT = 16:16 UTC) a failed
FCCMS search (timeout / 5xx) was stamped raw['divorce'] case_count 0, so an
unsearched lead read as "checked, no divorce". The old code only mis-stamped
while the portal was struggling, and a struggling portal leaves a signature:
tiny rounds. A healthy round stamped 200-1,300 leads; the overnight slow rounds
stamped 40-110. Re-searching a random sample of pre-fix person-owned negatives
found 0 of 112 hits for the healthy 9/17 stamps but 2 of 100 for 9/18, and both
hits sat in small rounds (51 and 75 leads).

Selects SC core-county, person-owned leads whose stamp says case_count 0 and whose
round (identical fetched_at across the board) is small and pre-fix, removes the
stamp, and leaves them in the never-checked pool for backfill_sc_divorce.py.
Positives are never touched. --dry-run (default) streams the board and only
counts; --apply needs the board in memory, so run it as the ONLY board process.

    python scripts/reset_divorce_slow_rounds.py            # count only
    python scripts/reset_divorce_slow_rounds.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_sc_divorce import _COUNTY_CODE  # noqa: E402
from foreclosure_scraper.name_normalize import is_entity  # noqa: E402

WINDOW_FROM = "2026-09-01"           # older stamps are past the 30-day refresh anyway
FIX_TS = "2026-09-18T16:16"          # ed15f11 committed 12:16 EDT: failed searches stop stamping
SMALL_ROUND_MAX = 120                # healthy rounds were 200-1,300 stamped leads


def in_scope(state, county, owner, divorce) -> bool:
    """A stamped SC core-county lead with an owner (person or company)."""
    return bool(divorce) and state == "SC" and (county or "").strip() in _COUNTY_CODE and bool(owner)


def suspect_rounds(round_sizes: dict[str, int]) -> set[str]:
    """fetched_at values that are small rounds written before the fix."""
    return {ts for ts, n in round_sizes.items()
            if WINDOW_FROM <= ts[:16] < FIX_TS and n <= SMALL_ROUND_MAX}


def is_suspect(state, county, owner, divorce, rounds: set[str]) -> bool:
    """A person-owned negative stamped in a suspect round. Positives and company
    names are left alone: a hit is a real case, a company is not a divorce party."""
    if not in_scope(state, county, owner, divorce):
        return False
    if divorce.get("case_count") != 0 or is_entity(owner):
        return False
    return divorce.get("fetched_at") in rounds


def _dry_run() -> int:
    from foreclosure_scraper.board_stream import iter_board_rows
    sizes: Counter = Counter()
    stamped = []
    for r in iter_board_rows():
        d = (r.get("raw") or {}).get("divorce")
        if in_scope(r.get("state"), r.get("county"), r.get("owner_name"), d):
            sizes[d.get("fetched_at") or ""] += 1
            stamped.append((r.get("state"), r.get("county"), r.get("owner_name"), d, r.get("source")))
    rounds = suspect_rounds(sizes)
    hit = [x for x in stamped if is_suspect(*x[:4], rounds)]
    print(f"suspect rounds: {len(rounds)}  (<= {SMALL_ROUND_MAX} stamped leads, {WINDOW_FROM} .. {FIX_TS} UTC)")
    print(f"person-owned negatives in them: {len(hit):,}")
    for src, c in Counter(str(x[4]) for x in hit).most_common(8):
        print(f"  {c:6,}  {src}")
    print("\nDRY RUN — nothing written. Re-run with --apply.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run()

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    with board_lock(REPO, owner="reset_divorce_slow_rounds"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        sizes: Counter = Counter()
        for li in rows:
            d = (li.raw or {}).get("divorce") if isinstance(li.raw, dict) else None
            if in_scope(li.state, li.county, li.owner_name, d):
                sizes[d.get("fetched_at") or ""] += 1
        rounds = suspect_rounds(sizes)
        targets = [li for li in rows if isinstance(li.raw, dict)
                   and is_suspect(li.state, li.county, li.owner_name, li.raw.get("divorce"), rounds)]
        print(f"board rows: {n:,}; suspect rounds: {len(rounds)}; clearing {len(targets):,} negative stamps")
        for li in targets:
            li.raw.pop("divorce", None)
            ds = li.raw.get("distress_stack")
            if isinstance(ds, dict) and isinstance(ds.get("categories"), list):
                ds["categories"] = [c for c in ds["categories"] if c != "divorce"]
        assert len(rows) == n
        write_artifact(rows, {"reset_divorce_slow_rounds": {"cleared": len(targets), "rounds": len(rounds)}},
                       docs_dir=REPO / "docs")
        print(f"cleared {len(targets):,} stamps; wrote board: {n:,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
