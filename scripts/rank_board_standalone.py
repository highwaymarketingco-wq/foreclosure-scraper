#!/usr/bin/env python3
"""Stamp raw['owner_name_signal'] and raw['fullmer'] on the live board without a full run.

WHY THIS EXISTS
    `rank_board` runs inside main.run(), so the rank only lands when a full scrape
    completes. The county coverage matrix on 2026-09-10 reported **ranked 0% in all
    18 footprint counties** -- not because ranking is broken but because no full run
    has landed since it was wired, and the board's recent writes came from targeted
    repair scripts that do not rank.

    Unranked, the board is 94,384 rows in arbitrary order. Ranked, it is a queue.
    That is the whole difference between data and a call list, and it should not have
    to wait for a 6-10 hour scrape.

Ranks, never trims: rank_board asserts the row count is unchanged and this script
asserts it again after the write.

    python scripts/rank_board_standalone.py --dry-run
    python scripts/rank_board_standalone.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.enrichment_owner_name_signal import enrich_owner_name_signal
    from foreclosure_scraper.fullmer_rank import rank_board
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    from foreclosure_scraper.config import ALL_COUNTIES

    footprint = {(c.state.upper(), c.name.replace(" County", "").strip().lower())
                 for c in ALL_COUNTIES}

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="rank_board")
    with lock:
        listings = load_board(REPO / "docs")
        before = len(listings)
        print(f"board rows: {before:,}")

        # OWNER-NAME SIGNAL FIRST, because rank_board reads it.
        #
        # Measured 2026-09-10: raw["owner_name_signal"] was present on ZERO board rows
        # while fullmer_rank.score() reads it for a 12-point owner_name_death factor.
        # Not because the enricher is broken -- because it only runs inside main.run(),
        # and no full scrape has landed since it was wired. Exactly the situation
        # raw["fullmer"] was in, which is why this script exists. It is pure string
        # classification over owner names already on the board: no network, no cost.
        ons = enrich_owner_name_signal(listings)
        assert len(listings) == before, "owner-name signal must not change the row count"
        print(f"owner_name_signal: {ons}")

        stats = rank_board(listings)
        assert len(listings) == before, "ranking must not change the row count"

        print(f"\nranked: {stats['ranked']:,}")
        for b, n in stats["buckets"].items():
            print(f"   {b:<12} {n:>7,}  {n / max(before, 1) * 100:>5.1f}%")

        # Footprint-only view: this is the queue the operator actually works.
        fp_buckets = Counter()
        fp_top: list[tuple[float, str]] = []
        for li in listings:
            key = ((li.state or "").upper(),
                   (li.county or "").replace(" County", "").strip().lower())
            if key not in footprint:
                continue
            r = (li.raw or {}).get("fullmer") or {}
            v = r.get("rank")
            if v is None:
                continue
            fp_buckets["A (70+)" if v >= 70 else "B (50-69)" if v >= 50
                       else "C (30-49)" if v >= 30 else "D (<30)"] += 1
            if v >= 60:
                fp_top.append((v, f"{li.county},{li.state} {(li.street_address or li.owner_name or '?')[:44]}"))
        fp_total = sum(fp_buckets.values())
        print(f"\nIN-FOOTPRINT ranked: {fp_total:,}")
        for b in ("A (70+)", "B (50-69)", "C (30-49)", "D (<30)"):
            n = fp_buckets.get(b, 0)
            print(f"   {b:<12} {n:>7,}  {n / max(fp_total, 1) * 100:>5.1f}%")
        fp_top.sort(reverse=True)
        print(f"\nin-footprint leads ranking 60+: {len(fp_top):,}")
        for v, label in fp_top[:15]:
            print(f"   {v:>5.1f}  {label}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(listings, {
            "total": len(listings),
            "notes": (f"owner-name signal + fullmer rank on {stats['ranked']:,} rows "
                      f"(A {stats['buckets']['A (70+)']:,} / "
                      f"B {stats['buckets']['B (50-69)']:,} / "
                      f"C {stats['buckets']['C (30-49)']:,} / "
                      f"D {stats['buckets']['D (<30)']:,})"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
