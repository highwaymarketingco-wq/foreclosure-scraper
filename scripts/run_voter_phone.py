#!/usr/bin/env python3
"""Run the NC voter-file phone match over the board.

Free and entirely LOCAL — the NCSBE bulk files are cached under data/ncvoter/, so
this costs no network and can run any time. It had simply not been re-run since
thousands of rows were added, and phone is the binding constraint on whether a
ranked lead is callable at all.

Conservative by design (see enrichment_voter_phone): name AND street must match, so
a hit is the same person at the same address. Absentee owners do not match here and
should not — their number is not in this file.

Every number is tagged source=ncsbe_voter + needs_dnc_scrub=True and is NOT
call-ready until scrubbed against the National DNC Registry.

    python scripts/run_voter_phone.py --dry-run
    python scripts/run_voter_phone.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_voter_phone import enrich_voter_phone  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def _has_phone(li) -> bool:
    return bool(isinstance(li.raw, dict) and (li.raw.get("owner_phone") or {}).get("phone"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="voter_phone")
    with lock:
        rows = load_board(REPO / "docs")
        n = len(rows)
        before = sum(1 for li in rows if _has_phone(li))
        stats = enrich_voter_phone(rows)
        after = sum(1 for li in rows if _has_phone(li))
        print(f"board {n:,} rows")
        print(f"  owner_phone before : {before:,}")
        print(f"  owner_phone after  : {after:,}")
        print(f"  GAIN               : {after - before:,}")
        print(f"  stats: { {k: v for k, v in stats.items() if k != 'index_size'} }")
        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == n, "row count changed — refusing to write"
        write_artifact(rows, {"voter_phone_gain": after - before}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {n:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
