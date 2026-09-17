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
MAX_ROUNDS_DEFAULT = 60  # safety backstop; ~34.7K targets / ~500-900 per round


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
            if stats.get("error") == "handshake_failed":
                print("FCCMS handshake failed — stopping (will resume cleanly next run).")
                break

        print(f"\n=== RESULTS === {totals}")
        write_artifact(rows, {"backfill_sc_divorce": totals}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
