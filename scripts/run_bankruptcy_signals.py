#!/usr/bin/env python3
"""Targeted bankruptcy cross-reference + tax-combo pass against the EXISTING board,
without a full main.py pipeline run.

WHY THIS EXISTS
    2026-09-29 (docs/dirty_deeds_synthesis_2026-09-10.md Tier B #28): enrichment_bankruptcy.py
    now ALSO queries a "long-open" window -- bankruptcy petitions filed 10-15 years ago with
    no recorded date_terminated (live-verified against the real CourtListener API: the
    existing recent-filings query, LOOKBACK_DAYS=180, structurally cannot reach this
    population). Every match (recent or long-open) now carries case_age_days/case_age_years/
    is_long_open (signal_freshness.bankruptcy_case_age). enrichment_bankruptcy_tax_combo.py is
    new: a pure join that flags raw['bankruptcy_tax_combo'] wherever a listing carries both a
    bankruptcy match and a real delinquent-tax balance.

    Both enrichers are now wired into main.py's normal pipeline, but the last full run landed
    2026-08-29 (docs/HANDOFF.md) and load_board() self-refuses on this board's real size
    (~2.5 GB on disk against 219,530+ rows -- see scripts/backfill_tax_owed_amount_owed.py's
    docstring for the measured ceiling). This script is the scoped equivalent, same shape as
    scripts/run_dew_lien_enrichment.py: read-only stream via board_stream.iter_board_rows(),
    land via web_artifact.patch_existing_rows(), never load_board()/write_artifact().

    The matching/joining logic itself is NOT reimplemented here -- it is imported unchanged
    from enrichment_bankruptcy / enrichment_bankruptcy_tax_combo, so this can never drift from
    what a real main.py pass would do.

BOARD I/O
    1. ONE streaming read pass over the board (board_stream.iter_board_rows(), never a
       materialized Listing list) building a LIGHT Listing.model_construct() per row that has
       a `defendant` (the only rows enrich_with_bankruptcy's name-index can use). Also tallies
       every row's dedupe_key() for the collision guard backfill_tax_owed_amount_owed.py /
       run_dew_lien_enrichment.py both use.
    2. enrich_with_bankruptcy(listings) once, in-memory, over the light listings -- this makes
       the live CourtListener calls (recent + long-open, all 4 courts) and mutates
       li.raw['bankruptcy'] in place for every match.
    3. enrich_bankruptcy_tax_combo(listings) once, in-memory, pure-local (reads the
       raw['tax_owed'] each row already carried on the board, plus the raw['bankruptcy'] step
       2 just set/updated).
    4. Diff each listing's raw['bankruptcy'] / raw['bankruptcy_tax_combo'] against what that
       row already had on the board (a rerun must not re-patch an unchanged match). Only
       CHANGED or NEW values become a patch; a dedupe_key() shared by more than one distinct
       board row is dropped from this run entirely (reported as `skipped_collision`), the same
       guard backfill_tax_owed_amount_owed.py and run_dew_lien_enrichment.py use.
    5. patch_existing_rows(), checkpointed, under board_lock().

USAGE
    .venv/bin/python scripts/run_bankruptcy_signals.py --dry-run
    scripts/with_board_lock.sh bankruptcy_signals -- \\
        .venv/bin/python scripts/run_bankruptcy_signals.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import foreclosure_scraper.enrichment_bankruptcy as eb  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_bankruptcy import enrich_with_bankruptcy  # noqa: E402
from foreclosure_scraper.enrichment_bankruptcy_tax_combo import (  # noqa: E402
    enrich_bankruptcy_tax_combo,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields patch_existing_rows()/append_new_rows() key on internally
#: (web_artifact._APPEND_SIG_FIELDS), plus defendant/source/raw which enrich_with_bankruptcy
#: and enrich_bankruptcy_tax_combo need to read/write.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
               "case_number", "source_url", "listing_type", "defendant", "source", "raw")

CHECKPOINT_EVERY = 20_000  # patches per patch_existing_rows() call


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


async def _no_recent_filings(c, court: str, token: str) -> list[dict]:
    """--skip-recent stand-in for enrichment_bankruptcy._fetch_recent_bankruptcies:
    no network call, empty result -- see that flag's help text for why."""
    return []


def _light_listing(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    if not isinstance(li.raw, dict):
        li.raw = {}
    return li


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after inspecting this many board rows (testing)")
    ap.add_argument("--skip-recent", action="store_true",
                     help="skip the recent-filings (180-day) pass and run only the "
                          "long-open discovery query. The recent pass re-fetches "
                          "every filing across 3 courts AND does one lazy chapter "
                          "lookup per DISTINCT matching filing (measured live "
                          "2026-09-29: several hundred sequential CourtListener "
                          "requests at this board's real match volume, throttled "
                          "~1.15s apart by http_client's per-host limiter -- many "
                          "minutes wall-clock). The long-open pass alone is ~20-45s "
                          "(4 courts, a couple hundred results total, chapter "
                          "already inline). Use this to land/verify the NEW "
                          "long-open + combo signals quickly without waiting on a "
                          "full re-match of the pre-existing recent-filing pool.")
    args = ap.parse_args()

    if args.skip_recent:
        eb._fetch_recent_bankruptcies = _no_recent_filings  # noqa: SLF001

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    docs = REPO / "docs"

    # --- 1) ONE streaming pass: build light listings + tally dedupe_key() collisions -------
    t0 = time.time()
    key_counts: Counter = Counter()
    listings: list[Listing] = []
    keys: list[str | None] = []
    before_bk: list[dict | None] = []
    before_combo: list[dict | None] = []
    scanned = 0
    skipped_no_defendant = 0
    skipped_no_key = 0

    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        if not rec.get("defendant"):
            skipped_no_defendant += 1
            continue
        light = _light_listing(rec)
        try:
            key = light.dedupe_key()
        except Exception:  # noqa: BLE001 - too malformed to key is simply skipped
            key = None
        if key is None:
            skipped_no_key += 1
            continue
        key_counts[key] += 1
        listings.append(light)
        keys.append(key)
        raw = light.raw if isinstance(light.raw, dict) else {}
        before_bk.append(dict(raw.get("bankruptcy")) if isinstance(raw.get("bankruptcy"), dict) else None)
        before_combo.append(dict(raw.get("bankruptcy_tax_combo"))
                             if isinstance(raw.get("bankruptcy_tax_combo"), dict) else None)
        if args.limit and scanned >= args.limit:
            break

    print(f"board scan: {scanned:,} rows -> {len(listings):,} with a defendant "
          f"(no defendant: {skipped_no_defendant:,}, no dedupe key: {skipped_no_key:,}) "
          f"({time.time() - t0:.1f}s)", flush=True)

    if not listings:
        print("nothing to match against -- stopping", flush=True)
        return 0

    # --- 2) live bankruptcy cross-reference (network: CourtListener, recent + long-open) ---
    t1 = time.time()
    asyncio.run(enrich_with_bankruptcy(listings))
    print(f"enrich_with_bankruptcy: {time.time() - t1:.1f}s", flush=True)

    # --- 3) pure-local bankruptcy+tax combo join --------------------------------------------
    combo_stats = enrich_bankruptcy_tax_combo(listings)
    print(f"enrich_bankruptcy_tax_combo: {combo_stats}", flush=True)

    # --- 4) diff against what each row already had; build patches --------------------------
    candidates: dict[str, dict] = {}
    signal_counts: Counter = Counter()
    long_open_new = 0
    combo_new = 0
    for li, key, old_bk, old_combo in zip(listings, keys, before_bk, before_combo):
        raw = li.raw if isinstance(li.raw, dict) else {}
        new_bk = raw.get("bankruptcy")
        new_combo = raw.get("bankruptcy_tax_combo")
        patch_raw: dict = {}
        if isinstance(new_bk, dict) and new_bk != old_bk:
            patch_raw["bankruptcy"] = new_bk
            signal_counts[new_bk.get("signal") or "?"] += 1
            if new_bk.get("is_long_open"):
                long_open_new += 1
        if isinstance(new_combo, dict) and new_combo != old_combo:
            patch_raw["bankruptcy_tax_combo"] = new_combo
            combo_new += 1
        if patch_raw:
            candidates[key] = {"raw": patch_raw}

    collision_keys = {k for k in candidates if key_counts[k] > 1}
    for k in collision_keys:
        del candidates[k]

    print(f"\ncandidate changes: {len(candidates) + len(collision_keys):,} "
          f"({len(collision_keys):,} dropped as dedupe_key collisions, "
          f"{len(candidates):,} landable)", flush=True)
    print(f"  new/updated bankruptcy matches by signal: {dict(signal_counts)}", flush=True)
    print(f"  of which is_long_open: {long_open_new:,}", flush=True)
    print(f"  new/updated bankruptcy_tax_combo: {combo_new:,}", flush=True)

    if args.dry_run:
        print("\nDRY RUN -- nothing written.", flush=True)
        return 0

    if not candidates:
        print("\nnothing landable -- board not written.", flush=True)
        return 0

    # --- 5) land, checkpointed --------------------------------------------------------------
    lock = board_lock(REPO, owner="bankruptcy_signals")
    with lock:
        items = list(candidates.items())
        applied_total = 0
        for i in range(0, len(items), CHECKPOINT_EVERY):
            chunk = dict(items[i:i + CHECKPOINT_EVERY])
            stats = patch_existing_rows(
                chunk,
                {"notes": f"run_bankruptcy_signals.py (Tier B #28 long-open + tax combo): "
                          f"chunk={i}"},
                docs_dir=docs,
            )
            applied_total += stats["applied"]
            print(f"  [checkpoint {i}] patched {stats['applied']}/{len(chunk)} "
                  f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)

        print(f"\n=== RESULTS ===")
        print(f"rows scanned: {scanned:,}")
        print(f"patches applied: {applied_total:,}")
        print(f"dropped as dedupe_key collisions: {len(collision_keys):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
