#!/usr/bin/env python3
"""Run enrichment_parcel_from_geo.enrich_parcel_from_geo over the live board.

This network enrichment step (SC -> SCDOT SC_Parcels, or Anderson's own county
ArcGIS layer now that SCDOT is token-walled; NC -> NC OneMap NC1Map_Parcels)
point-in-polygon resolves a parcel_id for any geo-bearing lead that lacks one.
It exists in the codebase but is not called by scripts/apply_board_fixes.py's
STEPS list, so it has not been run as part of this session's repair chains.
Idempotent: a lead that already carries a parcel_id is skipped by the function
itself, so re-running finds nothing left to do on already-resolved rows.

    python scripts/run_parcel_from_geo.py            # dry run (default): loads
                                                        the live board (read-only,
                                                        no write_artifact), runs
                                                        the resolver in-memory,
                                                        reports what WOULD change,
                                                        discards the result
    python scripts/run_parcel_from_geo.py --apply     # ONLY board process
                                                        (board_lock + load_board +
                                                        write_artifact)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import REPO, require_raw_keep  # noqa: E402


def _run(apply: bool) -> int:
    from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    require_raw_keep(["parcel_from_geo"])
    owner = "run_parcel_from_geo"
    with board_lock(REPO, owner=owner):
        rows = load_board(REPO / "docs")
        n = len(rows)
        before = sum(1 for li in rows if li.parcel_id)
        counts = asyncio.run(enrich_parcel_from_geo(rows))
        after = sum(1 for li in rows if li.parcel_id)
        assert len(rows) == n, "must never change the row count"
        print(f"board rows: {n:,}")
        print(f"parcel_id present before: {before:,}  after: {after:,}  (+{after - before:,})")
        print("counts:", counts)
        if not apply:
            print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process) to keep this.")
            return 0
        write_artifact(rows, {owner: counts}, docs_dir=REPO / "docs")
        print(f"wrote board: {n:,} rows")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (ONLY board process)")
    args = ap.parse_args()
    return _run(args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
