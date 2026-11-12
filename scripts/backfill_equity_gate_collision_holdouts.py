#!/usr/bin/env python3
"""One-off backfill: close the 9-row holdout left by scripts/backfill_contradicted_
arv_gate.py (commit 8f88a754), board_selfcheck.py's "no equity on a contradicted
ARV" invariant (currently 9, unchanged across the 2026-10-01 Gaston/Anderson/
Greenville backfills).

WHY THESE 9 ROWS SURVIVED THE ORIGINAL BACKFILL
    backfill_contradicted_arv_gate.py fixed 99 of 107 originally-affected rows via
    web_artifact.patch_existing_rows(), which matches by Listing.dedupe_key() and
    -- by design -- applies the SAME patch object to every board row sharing a key.
    That script's own COLLISION GUARD dropped any key seen more than once in its
    scan, specifically because a patch computed from ONE row's own raw['calc']/
    raw['equity'] is only safe to deliver by key if every row sharing that key
    would compute the SAME patch; rather than assume that, it dropped all 8 such
    keys (9 rows: one key, parcel:NC:buncombe:9751308996, has two colliding rows
    that both needed the fix) and left them for "retry once the underlying
    duplicate is fixed separately."

WHAT THIS SCRIPT VERIFIES BEFORE TOUCHING ANYTHING (not assumed)
    For every dedupe_key with more than one row on the board, every member's
    arv_flags/arv_expected are read from THAT member's own raw['calc'], run
    through the real enrichment_equity.equity_arv_trust()/withhold_equity()
    functions (same ones the original backfill used), and the resulting withheld-
    equity block is compared byte-for-byte across all members sharing the key.
    withhold_equity()'s replacement block carries no row-specific value (it only
    records WHY equity is withheld: trust level + flag names), so two rows that
    agree on arv_flags/arv_expected always compute an IDENTICAL replacement block,
    regardless of what each row's own prior equity figure was -- applying it to
    both is not "pushing one row's answer onto an unrelated one", it is applying
    the same already-correct answer to two records of the same disputed valuation.

    A live check of the actual 8 keys (2026-10-01) found every member in every
    group agrees: all 8 pairs/one triple share identical arv_flags and
    arv_expected, so applying the single verified patch to every member is
    content-for-content what a position-based rewrite (the technique scripts/
    repair_dedupe_key_collision.py used for a harder, different problem --
    recomputing a NEW valuation number that must be validated against a backup)
    would also produce, without needing that heavier full-board-rewrite
    machinery or a pre-change backup: there is no "fresh vs. revert" ambiguity
    here, because the gate is a pure, deterministic function of each row's own
    ALREADY-PUBLISHED calc/equity, not a recompute.

    If any key's members ever DISAGREE (arv_flags/arv_expected genuinely
    differ -- the real duplicate-identity ambiguity, same root cause as
    board_selfcheck's separate 983-row "duplicate identifiable properties"
    invariant), that key is skipped and reported, not guessed at: that case
    needs the duplicate itself resolved first, which is a human-judgment call
    this script correctly refuses to make.

BOARD I/O
    Identification is two streamed read-only passes over board_stream.
    iter_board_rows() -- pass 1 tallies every row's dedupe_key() (O(1) state per
    key, ~219k ints) and flags which keys carry a currently-bad row (contradicted/
    withheld trust level + equity.value present); pass 2 (only over rows whose key
    was flagged, a few dozen at most) collects every member's calc/equity to run
    the agreement check above. The actual write goes through the same, already-
    tested web_artifact.patch_existing_rows() the original backfill used --
    nothing here duplicates its board-rewrite internals.

USAGE
    .venv/bin/python scripts/backfill_equity_gate_collision_holdouts.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/backfill_equity_gate_collision_holdouts.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.valuation.grading import ARV_TRUST_BLOCKS_DERIVED  # noqa: E402
from foreclosure_scraper.enrichment_equity import (  # noqa: E402
    equity_arv_trust, withhold_equity,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, patch_existing_rows,
)

DOCS = REPO / "docs"

#: Same identity fields patch_existing_rows()/the original backfill use internally.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|"
         r"load_board|recompute_valuation|merge_duplicate_rows|board_manifest|"
         r"patch_vision_gemini|recompute_geo_imprecise|lrcpwa_refresh|daily_api_refresh|"
         r"sos_agent_refresh|backfill_contradicted_arv_gate|repair_dedupe_key_collision|"
         r"rescore_greenville|backfill_anderson|backfill_gaston"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _calc_of(rec: dict) -> dict:
    return ((rec or {}).get("raw") or {}).get("calc") or {}


def _equity_of(rec: dict) -> dict | None:
    eq = ((rec or {}).get("raw") or {}).get("equity")
    return eq if isinstance(eq, dict) else None


def _is_bad(rec: dict) -> bool:
    """Mirrors board_selfcheck.py's 'no equity on a contradicted ARV' check exactly:
    a CONTRADICTED arv_flag (which equity_arv_trust reclassifies as trust level
    'contradicted' or 'withheld', both in ARV_TRUST_BLOCKS_DERIVED) alongside a
    published equity value."""
    li = Listing.model_construct(raw=rec.get("raw") if isinstance(rec.get("raw"), dict) else {})
    level, _flags = equity_arv_trust(li)
    if level not in ARV_TRUST_BLOCKS_DERIVED:
        return False
    eq = _equity_of(rec)
    return eq is not None and eq.get("value") is not None


def _target_block_for(rec: dict) -> dict:
    """What withhold_equity() would publish for THIS row's own calc, regardless of
    this row's own current equity state (uses a synthetic equity value so the
    idempotent no-op branch in withhold_equity() never short-circuits the
    computation -- we want the BLOCK CONTENT, not whether this particular row
    needs writing)."""
    li = Listing.model_construct(raw=rec.get("raw") if isinstance(rec.get("raw"), dict) else {})
    level, flags = equity_arv_trust(li)
    probe = Listing.model_construct(raw={"equity": {"value": 1.0}})
    withhold_equity(probe, level, flags)
    return probe.raw["equity"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    t0 = time.time()
    lock = None
    if not args.dry_run:
        try:
            lock = board_lock(REPO, owner="backfill_equity_gate_collision_holdouts")
            lock.__enter__()
        except BoardLockBusy as exc:
            print(f"{exc} -- refusing to write.", file=sys.stderr)
            return 1

    try:
        return _run(args, t0)
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)


def _run(args, t0) -> int:
    path = DOCS / "listings.json.gz"

    # --- pass 1: tally every row's dedupe_key, flag which keys carry a bad row ---
    key_counts: Counter = Counter()
    bad_keys: set = set()
    n = 0
    for rec in iter_board_rows(path):
        n += 1
        key = _dedupe_key(rec)
        if key is None:
            continue
        key_counts[key] += 1
        if _is_bad(rec):
            bad_keys.add(key)

    print(f"[{time.strftime('%H:%M:%S')}] pass 1: scanned {n:,} rows in {time.time()-t0:.0f}s")
    print(f"  bad-equity keys found: {len(bad_keys)}")
    collision_keys = {k for k in bad_keys if key_counts[k] > 1}
    solo_keys = bad_keys - collision_keys
    print(f"    solo (no collision): {len(solo_keys)}")
    print(f"    collisions (>1 row shares this key): {len(collision_keys)}")

    pending: dict[str, dict] = {}
    skipped_disagreement: list[dict] = []

    # --- solo keys: exactly one row on the board carries this key, no cross-
    # contamination is even possible -- patch directly from that row's own data. ---
    if solo_keys:
        for rec in iter_board_rows(path):
            key = _dedupe_key(rec)
            if key in solo_keys and key not in pending:
                pending[key] = {"raw": {"equity": _target_block_for(rec)}}

    # --- collision keys: pass 2, collect every member, verify agreement before
    # trusting a single patch to be correct for every row that shares the key. ---
    if collision_keys:
        members: dict[str, list[dict]] = {k: [] for k in collision_keys}
        for rec in iter_board_rows(path):
            key = _dedupe_key(rec)
            if key in collision_keys:
                members[key].append(rec)

        for key, rows in members.items():
            blocks = [_target_block_for(r) for r in rows]
            if all(b == blocks[0] for b in blocks):
                pending[key] = {"raw": {"equity": blocks[0]}}
            else:
                skipped_disagreement.append({
                    "dedupe_key": key,
                    "members": [
                        {"source": r.get("source"), "street_address": r.get("street_address"),
                         "parcel_id": r.get("parcel_id"),
                         "arv_flags": _calc_of(r).get("arv_flags"),
                         "arv_expected": _calc_of(r).get("arv_expected")}
                        for r in rows
                    ],
                })

    print(f"\n  patch-ready keys: {len(pending)}")
    print(f"  skipped as genuine disagreement (needs human judgment): {len(skipped_disagreement)}")
    if skipped_disagreement:
        print("\n--- disagreement detail (NOT patched) ---")
        for item in skipped_disagreement:
            print(f"  {item}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        print(f"  would patch {len(pending)} dedupe_key(s)")
        return 0

    if not pending:
        print("\nnothing to patch")
        return 0

    stats = patch_existing_rows(
        pending,
        {"backfill_equity_gate_collision_holdouts": len(pending),
         "notes": (f"re-gate equity on {len(pending)} dedupe_key-collision keys left "
                   f"unpatched by backfill_contradicted_arv_gate.py (8f88a754); all "
                   f"members verified to agree on arv_flags/arv_expected before patching "
                   f"({len(skipped_disagreement)} disagreeing keys skipped, none found "
                   f"today)")},
        docs_dir=DOCS,
    )
    print(f"\n[{time.strftime('%H:%M:%S')}] patched {stats['applied']}/{len(pending)} keys "
          f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
          f"dup_keys: {stats['duplicate_key_matches']:,}) in {time.time()-t0:.0f}s total",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
