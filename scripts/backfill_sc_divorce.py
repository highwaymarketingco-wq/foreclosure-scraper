#!/usr/bin/env python3
"""Chunked, checkpointed runner for enrich_sc_divorce() over the whole board.

Found 2026-09-16: enrich_sc_divorce() is default-ON, free, live-verified,
fully compliant (public FCCMS PublicAccess party-name search, no CAPTCHA/
login defeated) — but it self-caps at FORECLOSURE_SC_DIVORCE_MAX (default
400) leads per run, sized for incremental nightly operation. A one-time dry
check (max_lookups=0, zero network calls) showed 31,036 of the ~34,714
eligible SC core-county leads (Spartanburg/Anderson/Pickens/Oconee/Cherokee/
Union/Laurens) have NEVER been checked. At the default cap that's ~78
nightly runs to reach parity; this script sweeps it in one campaign instead,
the same shape as backfill_flood_zone.py.

enrich_sc_divorce() already handles its own target selection (SC + core
county + has owner_name + stale), HOT/stale-first ordering, and a 1800s
internal wall-clock budget per call — so each call below naturally processes
however many leads fit in ~30 minutes regardless of the cap passed, and is
idempotent (skips anything already fetched within the refresh window). This
script just loops calls and checkpoints the board between them so an
interrupted run loses no progress.

    python scripts/backfill_sc_divorce.py --dry-run
    python scripts/backfill_sc_divorce.py
    python scripts/backfill_sc_divorce.py --max-rounds 3   # testing
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_sc_divorce import enrich_sc_divorce  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

PER_CALL_CAP = 3000  # upper bound; the enricher's own 1800s budget governs actual throughput
# A round must search at least this many leads to count as low-yield. Was 300,
# sized for full-speed rounds of ~1,000+. With the portal at ~9s per search a
# 30-minute round tops out around 200, so at 300 the rule could never fire and
# a run whose good leads were exhausted would keep searching until the
# supervisor's deadline. 100 searches at <1% is at most one hit; two such
# rounds in a row is the stop signal.
LOW_YIELD_MIN_SEARCHED = 100
LOW_YIELD_RATE = 0.01         # ...and find under 1% hits to count as low-yield
LOW_YIELD_ROUNDS = 2          # consecutive low-yield rounds before stopping
MAX_ROUNDS_DEFAULT = 60  # safety backstop; ~34.7K targets / ~500-900 per round


def stop_decision(stats: dict, low_rounds: int) -> tuple[bool, str, int]:
    """(stop?, reason, new consecutive-low-yield count) after one enrich round.

    A throttle abort stops the run: the enricher's 12-consecutive-failure guard
    means FCCMS is failing calls, and starting the next round immediately
    (re-handshake, another ~1,000 requests) just keeps pushing on a portal that
    is already pushing back. Found 2026-09-18: round 4 aborted with 51 errors
    and the script, which only checked for a failed handshake, went straight on.
    """
    if stats.get("error") == "handshake_failed":
        return True, "FCCMS handshake failed — stopping (resumable).", low_rounds
    if stats.get("aborted_throttled"):
        return True, ("FCCMS is failing calls (throttle guard tripped after "
                      f"{stats.get('errors', 0)} errors) — stopping so the portal can "
                      "recover; rerun later (resumable)."), low_rounds
    low = (stats.get("searched", 0) >= LOW_YIELD_MIN_SEARCHED and
           stats.get("with_divorce", 0) / max(1, stats["searched"]) < LOW_YIELD_RATE)
    low_rounds = low_rounds + 1 if low else 0
    if low_rounds >= LOW_YIELD_ROUNDS:
        return True, (f"{low_rounds} consecutive rounds under {LOW_YIELD_RATE:.0%} hit rate "
                      "— remaining leads are low-yield, stopping (resumable)."), low_rounds
    return False, "", low_rounds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-rounds", type=int, default=MAX_ROUNDS_DEFAULT)
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_sc_divorce")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        dry_stats = asyncio.run(enrich_sc_divorce(rows, max_lookups=0))
        print(f"pending (never-checked or stale): {dry_stats['pending']:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        totals = {"searched": 0, "with_divorce": 0, "cases_found": 0, "errors": 0}
        round_n = 0
        low_rounds = 0
        while round_n < args.max_rounds:
            round_n += 1
            stats = asyncio.run(enrich_sc_divorce(rows, max_lookups=PER_CALL_CAP))
            for k in totals:
                totals[k] += stats.get(k, 0)
            print(f"round {round_n}: {stats}  (running totals: {totals})", flush=True)

            write_artifact(rows, {"backfill_sc_divorce_checkpoint": totals}, docs_dir=REPO / "docs")
            print(f"  [checkpoint] wrote board after round {round_n}", flush=True)

            if stats.get("targets", 0) == 0 or stats.get("pending", 0) == 0:
                print("no targets left this round — backfill complete.")
                break
            stop, reason, low_rounds = stop_decision(stats, low_rounds)
            if stop:
                print(reason, flush=True)
                break

        print(f"\n=== RESULTS === {totals}")
        write_artifact(rows, {"backfill_sc_divorce": totals}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
