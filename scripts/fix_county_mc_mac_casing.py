#!/usr/bin/env python3
"""Detect (and, with --apply, correct) county names still mis-cased by a bare `.title()` call.

ROOT CAUSE (found 2026-09-28): county_name.canonical_county() was added 2026-09-13 (commit
ffa7956) after `.title()` was found silently splitting "McDowell" -> "Mcdowell" (and always
corrupting "McCormick" -> "Mccormick", since `.title()` lowercases every letter after the first
of each word). scripts/canonicalize_board_counties.py corrected the LIVE BOARD ONCE that day.
But that fix only ever touched the snapshot: the scraper write paths that PRODUCE the `county`
field were never switched over to canonical_county(), so any scraper still calling `.title()` on
a fresh "MCDOWELL COUNTY" / "mcdowell" string reintroduces the exact same wrong spelling on
every new row it writes -- the bug is not fixed, it is just re-won every time the board is
reloaded.

docs/completeness_audit_2026-09-27.md flagged this drift as still live two weeks later: "10 of
McDowell NC's 2,700 rows carry the casing error". Tracing those 10 rows on the live board by
their `source` field shows all ten are `national.fannie_homepath`:

    src/foreclosure_scraper/scrapers/national/fannie_homepath.py:112 (before this fix)
        county=(p.get("county") or "").replace(" COUNTY", "").title() or None,

Its sibling endpoint has the byte-for-byte identical bug and just hadn't produced a McDowell row
in this snapshot:

    src/foreclosure_scraper/scrapers/national/homepath_json.py:139 (before this fix)
        county=(p.get("county") or "").replace(" COUNTY", "").title() or None,

Both call sites now use county_name.canonical_county() instead of `.title()`, so new rows from
those two scrapers can no longer mis-case McDowell/McCormick. This script is the companion DRIFT
DETECTOR / one-shot corrector: a check (and, with --apply, a fix) for any row on the live board
-- from those two scrapers, or from any other `.title()`-on-county call site not yet audited
(there are over a dozen; see county_name.py's own docstring) -- whose county string is not
already canonical_county()'s spelling. It complements, and does not replace,
scripts/canonicalize_board_counties.py: that script re-title-cases every county wholesale
through the older load_board()/write_artifact() path with no dry-run-safe streaming mode; this
one is read-only by default (never calls load_board), reports exactly which rows/sources are
wrong, and --apply touches only the rows that are actually wrong.

Fills/repairs only: never adds or removes a row, never changes any field but `county`. Re-running
immediately after --apply finds zero rows left to fix (idempotent).

    python scripts/fix_county_mc_mac_casing.py                    # dry run (default): streams
                                                                    # the live board read-only,
                                                                    # PRINTS what it would fix,
                                                                    # writes nothing
    python scripts/fix_county_mc_mac_casing.py --apply             # ONLY board process
                                                                    # (board_lock + load_board +
                                                                    # write_artifact)
    python scripts/fix_county_mc_mac_casing.py --rows-file x.jsonl # dry run over a saved extract
                                                                    # instead of the live board
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import iter_rows, print_counter  # noqa: E402


def _src(s) -> str:
    return str(s or "").split(".")[-1]


# --------------------------------------------------------------------------------------- dry run
def _dry_run(rows_file: str | None) -> int:
    from foreclosure_scraper.county_name import canonical_county

    n = 0
    by_spelling: Counter = Counter()
    by_source: Counter = Counter()
    samples: list[tuple[str, str, str]] = []

    for r in iter_rows(rows_file):
        cur = (r.get("county") or "").strip()
        if not cur:
            continue
        canon = canonical_county(cur)
        if not canon or canon == cur:
            continue
        n += 1
        src = _src(r.get("source"))
        by_spelling[f"{cur!r} -> {canon!r}"] += 1
        by_source[src] += 1
        if len(samples) < 10:
            samples.append((src, cur, canon))

    print(f"mis-cased county rows found: {n:,}")
    if n:
        print_counter(by_spelling, "\nBY SPELLING (current -> canonical)")
        print_counter(by_source, "\nBY SOURCE")
        print("\nsample rows (source, current, canonical):")
        for s in samples:
            print(f"  {s}")
    print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process) to fix.")
    return 0


# ----------------------------------------------------------------------------------------- apply
def apply_rows(rows: list, *, dry_run: bool = False) -> dict:
    """Rewrite `li.county` to county_name.canonical_county(li.county) wherever they differ.

    Never adds/removes a row, never touches any field but `county`. dry_run=True mutates nothing
    (kept for symmetry with the other _dq_common-style fix modules and so this function can be
    slotted into scripts/apply_board_fixes.py's STEPS list; the CLI's own dry run above uses the
    cheaper streaming path in _dry_run and never calls this)."""
    from foreclosure_scraper.county_name import canonical_county

    n = len(rows)
    c: Counter = Counter()
    for li in rows:
        cur = (li.county or "").strip()
        if not cur:
            continue
        canon = canonical_county(cur)
        if canon and canon != cur:
            c[f"{_src(li.source)}: {cur!r} -> {canon!r}"] += 1
            if not dry_run:
                li.county = canon
    assert len(rows) == n, "a county recase must never change the row count"
    return dict(c)


def _apply() -> int:
    from _dq_common import run_apply
    # No raw key is written by this fix (only li.county changes), so there is nothing to
    # register in web_artifact.RAW_KEEP and the required_keys list is empty.
    return run_apply("fix_county_mc_mac_casing", apply_rows, [], "fix_county_mc_mac_casing")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="write the board (ONLY board process)")
    ap.add_argument("--rows-file", help="dry run over a saved JSONL extract instead of the live board")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run(args.rows_file)
    if args.rows_file:
        raise SystemExit("--rows-file is dry-run only")
    return _apply()


if __name__ == "__main__":
    raise SystemExit(main())
