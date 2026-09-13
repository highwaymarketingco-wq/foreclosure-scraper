#!/usr/bin/env python3
"""Strip qPayBill's zero-padded city/ZIP columns from addresses already on the board.

Several qPayBill portals render an absent city and ZIP as literal zeros, so rows
landed as "9523 HWY 260 0 0000". The scraper now cleans this at parse time
(_clean_situs); this repairs the 4,327 rows that predate the fix.

A row whose address was NOTHING but padding has its street_address cleared — the
truth is that it has no address, and a row that looks like it has one is worse:
it is never sent for resolution and never gets a real address.

    python scripts/clean_qpaybill_situs_padding.py --dry-run
    python scripts/clean_qpaybill_situs_padding.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import _clean_situs  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import contextlib
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="situs_pad")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        c = Counter()
        examples: list[tuple[str, str]] = []
        # SCOPED TO THE SOURCE THIS BUG CAME FROM. The first version of this script
        # ran over every row and, because _clean_situs also .strip()s, it silently
        # proposed edits to ~60 NC rows from other scrapers whose only problem was
        # surrounding whitespace. Trimming those is probably fine, but it is a
        # different change than the one diagnosed here, so it is not smuggled in.
        # (Noted separately in the queue doc.)
        for li in rows:
            if "qpaybill" not in (li.source or ""):
                continue
            addr = li.street_address
            if not addr:
                continue
            cleaned = _clean_situs(addr)
            if cleaned == addr:
                continue
            c["changed"] += 1
            c[f"county:{li.county}"] += 1
            if cleaned is None:
                c["cleared (was padding only)"] += 1
            if len(examples) < 8:
                examples.append((addr, cleaned or "<cleared>"))
            if not args.dry_run:
                li.street_address = cleaned

        print(f"\nrows to change: {c['changed']:,}")
        print(f"  of which cleared entirely: {c['cleared (was padding only)']:,}")
        for k, v in sorted(c.items()):
            if k.startswith("county:"):
                print(f"    {k[7:]:16} {v:,}")
        print("\nexamples:")
        for before, after in examples:
            print(f"    {before!r:36} -> {after!r}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        if not c["changed"]:
            print("\nnothing to do.")
            return 0
        write_artifact(rows, {"situs_padding_cleaned": c["changed"]}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows, {c['changed']:,} addresses repaired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
