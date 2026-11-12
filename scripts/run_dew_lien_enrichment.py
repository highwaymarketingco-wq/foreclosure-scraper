#!/usr/bin/env python3
"""Targeted SC DEW lien cross-reference pass against the EXISTING board, without a full
main.py pipeline run.

WHY THIS EXISTS
    2026-09-29 commit 2b780229 fixed sc_dew_lien_registry._to_listing()'s admission gate from
    config.in_scope() (the narrow 7-county SC flip footprint + a 5-county coastal allowlist) to
    config.in_scope_distressed() (every real NC/SC county) -- see that module's docstring and
    tests/test_sc_dew_lien_footprint_widen.py. That scraper is disabled=True as a board source
    (verified live: `run_scoped_scrapers.py --slugs counties_sc.sc_dew_lien_registry` returns
    outcome DORMANT, 0 rows -- safe_run() short-circuits on `disabled` before any network call).
    It exists purely as a NAME cross-reference: enrichment_dew_liens.enrich_dew_liens() calls
    SCDEWLienRegistry().fetch() directly and attaches matching liens to EXISTING property leads
    by (county, owner-name-tokens) -- it never emits new board rows.

    Confirmed live (read-only probe) that the widened gate actually surfaces real rows in
    previously-excluded counties: of 5,244 in-footprint rows returned by one .fetch() call,
    2,330 (44%) are in the 12 counties outside the OLD footprint, including real named,
    balance-bearing liens in 3 of the 17-county "thin coverage" cluster
    (docs/completeness_audit_2026-09-29.md section 3): Greenwood 56, Darlington 52,
    Chesterfield 21.

    So the fix needs an actual enrichment pass to attach anything -- it only widens what
    .fetch() is ALLOWED to return, it does not retroactively touch the board by itself. Nothing
    calls enrich_dew_liens() against the live 219k-row board outside a full main.py run, and the
    last full run landed 2026-08-29 (docs/HANDOFF.md). This script is the scoped equivalent, in
    the same shape as scripts/run_pending_signal_enrichers.py (same class of task: run one
    already-wired enricher against the existing board without a full pipeline pass) but using
    the newer, safer board I/O this board's real size now requires: load_board() self-refuses
    above BOARD_LOAD_MAX_SOURCE_MB (measured ~11 GB physical footprint against 219,530 rows --
    see scripts/backfill_tax_owed_amount_owed.py's docstring), so the board is streamed
    read-only via board_stream.iter_board_rows() and landed with
    web_artifact.patch_existing_rows() (task_0658b33b pattern), never load_board()/write_artifact().

    The matching logic itself (index build, county+name-token join, the >=3-token
    non-business gate, the idempotent "already has a sc_dew_lien_registry lien" skip) is
    NOT reimplemented here -- it is imported unchanged from enrichment_lien_stack /
    enrichment_dew_liens so this can never drift from what a real main.py pass would do.

BOARD I/O
    1. SCDEWLienRegistry().fetch() once (live network call, ~90s, ~16 MB) -- builds the
       (county, owner-name-tokens) -> balance index exactly as enrich_dew_liens() does.
    2. ONE streaming read pass over the board (board_stream.iter_board_rows(), ~295 MB peak,
       never a materialized Listing list): every row's dedupe_key() is computed from a light
       Listing.model_construct() of just the identity + owner fields (no pydantic validation);
       a match builds a candidate patch that APPENDS to (never replaces) that row's existing
       raw['liens'] list. Same COLLISION GUARD as backfill_tax_owed_amount_owed.py: a
       dedupe_key() shared by more than one DISTINCT board row is dropped from this run
       entirely (reported as `skipped_collision`) rather than applying the same patch to an
       unrelated row.
    3. patch_existing_rows(), checkpointed, under board_lock(). Idempotent: a second run only
       adds newly-eligible matches (a lead added since the last pass, a lien this run's fetch
       returned that a prior run's didn't); a row already carrying a sc_dew_lien_registry lien
       is left untouched.

USAGE
    .venv/bin/python scripts/run_dew_lien_enrichment.py --dry-run
    scripts/with_board_lock.sh dew_lien_enrichment -- \\
        .venv/bin/python scripts/run_dew_lien_enrichment.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_lien_stack import _name_tokens, _owner_tokens, _is_business  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.sc_dew_lien_registry import SCDEWLienRegistry  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields patch_existing_rows()/append_new_rows() key on internally
#: (web_artifact._APPEND_SIG_FIELDS), plus the two fields _owner_tokens() and the
#: TAX_LIEN skip need. Kept as a local literal rather than importing a private symbol.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type", "defendant", "raw")

CHECKPOINT_EVERY = 20_000  # rows scanned between patch_existing_rows() writes


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _light_listing(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})


async def _build_index(rows) -> dict[tuple[str, frozenset], float]:
    """Same index enrichment_dew_liens.enrich_dew_liens() builds, over real .fetch() rows."""
    index: dict[tuple[str, frozenset], float] = {}
    for r in rows:
        d = (r.raw or {}).get("sc_dew_lien_registry") or {}
        toks = _name_tokens(r.defendant)
        if len(toks) < 3 or _is_business(toks):
            continue
        amt = d.get("balance") or r.judgment_amount
        if not amt:
            continue
        key = ((r.county or "").upper(), toks)
        index[key] = max(index.get(key, 0.0), float(amt))
    return index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after inspecting this many board rows (testing)")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    docs = REPO / "docs"

    # --- 1) live DEW fetch (network, ~90s) -------------------------------------------------
    t0 = time.time()
    dew_rows = list(asyncio.run(SCDEWLienRegistry().fetch()))
    print(f"DEW fetch: {len(dew_rows):,} in-footprint lien rows ({time.time() - t0:.1f}s)",
          flush=True)
    by_dew_county: Counter = Counter((r.county or "NONE") for r in dew_rows)
    print("  top counties:",
          dict(sorted(by_dew_county.items(), key=lambda kv: -kv[1])[:10]))

    index = asyncio.run(_build_index(dew_rows))
    print(f"  usable (>=3-token, non-business, has $) index entries: {len(index):,}",
          flush=True)
    if not index:
        print("nothing to match -- stopping", flush=True)
        return 0

    # --- 2) ONE streaming pass over the board: identity-match + collision tally -----------
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="dew_lien_enrichment")

    with lock:
        key_counts: Counter = Counter()
        candidates: dict[str, dict] = {}       # dedupe_key -> patch
        matched_county: Counter = Counter()
        scanned = 0
        skipped_no_key = 0
        skipped_tax_lien = 0
        skipped_already_tagged = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            light = _light_listing(rec)
            try:
                key = light.dedupe_key()
            except Exception:  # noqa: BLE001 - too malformed to key is simply skipped
                key = None
            if key is None:
                skipped_no_key += 1
            else:
                key_counts[key] += 1
                if rec.get("listing_type") == "tax_lien":
                    skipped_tax_lien += 1
                else:
                    toks = _owner_tokens(light)
                    if len(toks) >= 3:
                        amt = index.get(((rec.get("county") or "").upper(), toks))
                        if amt:
                            raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
                            liens = list(raw.get("liens") or [])
                            if any(x.get("source") == "sc_dew_lien_registry" for x in liens):
                                skipped_already_tagged += 1
                            else:
                                liens.append({
                                    "type": "dew_lien", "amount": round(float(amt), 2),
                                    "source": "sc_dew_lien_registry",
                                    "holder": "SC Dept of Employment & Workforce",
                                    "super_priority": True,
                                })
                                candidates[key] = {"raw": {"liens": liens}}
                                matched_county[rec.get("county") or "NONE"] += 1
            if args.limit and scanned >= args.limit:
                break

        collision_keys = {k for k in candidates if key_counts[k] > 1}
        for k in collision_keys:
            del candidates[k]

        print(f"\nboard scan: {scanned:,} rows "
              f"(no dedupe key: {skipped_no_key:,}, tax_lien rows skipped: {skipped_tax_lien:,}, "
              f"already tagged: {skipped_already_tagged:,})", flush=True)
        print(f"candidate matches: {len(candidates) + len(collision_keys):,} "
              f"({len(collision_keys):,} dropped as dedupe_key collisions, "
              f"{len(candidates):,} landable)", flush=True)
        print("matches by county:",
              dict(sorted(matched_county.items(), key=lambda kv: -kv[1])[:20]), flush=True)

        if args.dry_run:
            print("\nDRY RUN -- nothing written.", flush=True)
            return 0

        if not candidates:
            print("\nnothing landable -- board not written.", flush=True)
            return 0

        # --- 3) land, checkpointed ---------------------------------------------------------
        items = list(candidates.items())
        applied_total = 0
        for i in range(0, len(items), CHECKPOINT_EVERY):
            chunk = dict(items[i:i + CHECKPOINT_EVERY])
            stats = patch_existing_rows(
                chunk,
                {"notes": f"run_dew_lien_enrichment (2026-09-29 footprint-widen follow-up): "
                          f"chunk={i}"},
                docs_dir=docs,
            )
            applied_total += stats["applied"]
            print(f"  [checkpoint {i}] patched {stats['applied']}/{len(chunk)} "
                  f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)

        print(f"\n=== RESULTS ===")
        print(f"rows scanned: {scanned:,}")
        print(f"DEW liens attached: {applied_total:,}")
        print(f"dropped as dedupe_key collisions: {len(collision_keys):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
