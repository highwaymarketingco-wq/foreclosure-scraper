#!/usr/bin/env python3
"""Backfill owner_name for existing sc_dew_lien_registry rows that only carry defendant.

The scraper set defendant=name but never owner_name=name, even though the DEW
registrant IS the property owner -- unlike a bankruptcy case caption, this source's
`name` field is a clean party name (verified in source 2026-09-14). Every
owner_name-keyed enricher (absentee derivation, voter-phone match, dedupe) was
blind to these 486 Anderson rows and however many exist elsewhere. The scraper is
fixed for future runs; this backfills what is already on the board.

    python scripts/backfill_dew_owner_name.py --dry-run
    python scripts/backfill_dew_owner_name.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="dew_owner_backfill")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        c = Counter()
        for li in rows:
            if li.source != "counties_sc.sc_dew_lien_registry":
                continue
            if li.owner_name or not li.defendant:
                continue
            c["backfilled"] += 1
            c[f"county:{li.county}"] += 1
            if not args.dry_run:
                li.owner_name = li.defendant

        print(f"\nbackfilled: {c['backfilled']:,}")
        for k, v in c.most_common():
            if k.startswith("county:"):
                print(f"    {k[7:]:16} {v:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        if not c["backfilled"]:
            print("\nnothing to do.")
            return 0
        assert len(rows) == before, "row count changed — refusing to write"
        write_artifact(rows, {"dew_owner_backfill": c["backfilled"]}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged, {c['backfilled']:,} owner_name filled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
