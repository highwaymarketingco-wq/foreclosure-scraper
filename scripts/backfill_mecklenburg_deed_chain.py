#!/usr/bin/env python3
"""--county/--state-scoped variant of scripts/backfill_deed_chain_v2.py's board-wide
enrich_deed_chain() backfill, built for the gap_matrix 2026-11-11 run's "built-but-low-yield"
entries on Mecklenburg NC: atty_deed_chain_fetched, deed_chain_has_history, deed_chain_break,
deed_chain_distress_transfer (39,799 rows each -- all four read the SAME raw['deed_chain']
this one producer writes, so one backfill closes all four gap_list rows at once).

WHY A NEW SCRIPT INSTEAD OF JUST RE-RUNNING v2
    backfill_deed_chain_v2.py (2026-10-22) already does exactly this -- streamed, two-pass,
    bounded-memory, patch_existing_rows() -- BOARD-WIDE, with no county filter. Re-running it
    would also close Mecklenburg's gap (and every other county's at the same time). This script
    exists because the orchestrating session asked for a reusable --county/--state-scoped tool,
    not because v2 is wrong or stale -- it reuses v2's exact proven mechanics line for line where
    they apply; the only real addition is the scope filter in pass 2. The dry-run numbers below
    tell you whether Mecklenburg specifically has anything left to gain from this at all; if the
    gain is board-wide (every county's upstream feeders have grown since 10/22), re-running v2
    once is the better move than one scoped script per county.

enrich_deed_chain() ITSELF (verified by reading it, not assumed from the gap_matrix doc string):
    100% OFFLINE, no network calls -- it only reorganizes raw['assessor_card'].sales,
    raw['county_sales'].sales, raw['gis'].last_sale, raw['rod_docs'] and raw['relationship_signal']
    (all written by OTHER, already-run enrichers) into a per-row chronological chain + summary at
    raw['deed_chain'] = {transfers, summary}. atty_deed_chain_fetched checks transfers is non-empty;
    deed_chain_has_history / deed_chain_break / deed_chain_distress_transfer all read fields inside
    `summary` the SAME call computes. So this is a pure function over one Listing, with exactly ONE
    genuinely whole-board dependency: `shared_pts` (block_binding.shared_points()), used to detect a
    shared/fallback geocode point so a row sitting on one does not inherit a DIFFERENT parcel's sale
    history. That dependency is NOT county-scoped -- a Mecklenburg row can share a point with a row
    in another county, or with another Mecklenburg row this run's own batching would otherwise split
    apart -- so PASS 1 below still scans the WHOLE board for (lat,lng) clustering, exactly as v2
    does. Only pass 2's eligibility/patch set is scoped to --county/--state (cheap: rows outside the
    scope are skipped before a Listing is even built for them, unlike v2's unconditional batching).

BOARD I/O: identical to v2 -- board_stream.iter_board_rows() (never load_board()), bounded
--batch-size-row batches (default 20,000, same CHECKPOINT_EVERY convention as
backfill_tax_aging_surfaced.py), light Listing.model_construct() carrying only raw/latitude/
longitude plus the identity fields dedupe_key() needs, patches keyed by dedupe_key() via
patch_existing_rows(), BOARD_PATCH_ALLOW_LARGE=1 / --allow-large gate (board_patch_size_state()).

    python scripts/backfill_mecklenburg_deed_chain.py --dry-run
    python scripts/backfill_mecklenburg_deed_chain.py --dry-run --county Mecklenburg --state NC
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_mecklenburg_deed_chain.py   # real write, on the VM
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.block_binding import FALLBACK_POINT_MIN_ROWS  # noqa: E402
from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "latitude", "longitude")


def _point(rec: dict):
    lat, lng = rec.get("latitude"), rec.get("longitude")
    try:
        return (round(float(lat), 5), round(float(lng), 5))
    except (TypeError, ValueError):
        return None


def _compute_shared_points(docs_dir: Path) -> set:
    """Pass 1: (lat,lng) clustering over the WHOLE board -- see module docstring for why this
    cannot be scoped to --county without risking a wrong fallback-point verdict on a row whose
    cluster-mate sits in a different county."""
    from collections import Counter
    n: Counter = Counter()
    total = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        p = _point(rec)
        if p is not None:
            n[p] += 1
        total += 1
    print(f"pass 1: {total:,} board rows scanned for (lat,lng) clustering (whole board, "
          f"not scoped -- see module docstring)")
    return {p for p, c in n.items() if c >= FALLBACK_POINT_MIN_ROWS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=20000)
    ap.add_argument("--state", default="NC", help="Restrict pass 2 to one state (default NC)")
    ap.add_argument("--county", default="Mecklenburg",
                    help="Restrict pass 2 to one county (default Mecklenburg). Pass '' for "
                         "board-wide (then just use backfill_deed_chain_v2.py instead).")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    want_state = (args.state or "").strip().upper() or None
    want_county = (args.county or "").strip() or None

    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        print(f"board_patch_size_state: {size_state}")
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
    else:
        # Informational only in dry-run -- patch_existing_rows() is never called, so nothing is
        # actually gated on this, but the task's own size-ceiling question deserves a real answer.
        print(f"board_patch_size_state (informational, dry-run never calls patch_existing_rows): "
              f"{board_patch_size_state(docs_dir)}")

    shared_pts = _compute_shared_points(docs_dir)
    print(f"shared fallback points (whole board): {len(shared_pts):,}")

    total_rows = 0
    in_scope_rows = 0
    before_count = 0
    after_count = 0
    cleared_count = 0
    new_count = 0
    refreshed_count = 0
    total_patched = 0
    collisions = 0
    batch: list[tuple[str | None, Listing, bool]] = []

    def flush(batch: list[tuple[str | None, Listing, bool]]) -> None:
        nonlocal after_count, total_patched, cleared_count, new_count, refreshed_count, collisions
        if not batch:
            return
        listings = [li for _, li, _ in batch]
        enrich_deed_chain(listings, shared_pts=shared_pts)
        patches: dict[str, dict] = {}
        for key, li, had_before in batch:
            if key is None:
                collisions += 1  # no usable identity at all -- counted, never guessed at
                continue
            has_now = isinstance(li.raw, dict) and isinstance(li.raw.get("deed_chain"), dict)
            if has_now:
                after_count += 1
            if has_now and not had_before:
                new_count += 1
                patches[key] = {"raw": {"deed_chain": li.raw["deed_chain"]}}
            elif had_before and not has_now:
                # enrich_deed_chain() deliberately pops a stale deed_chain built from a
                # fallback-point-contaminated source when it finds no genuine records this pass --
                # must propagate the removal, not just skip it (same as v2).
                cleared_count += 1
                patches[key] = {"raw": {"deed_chain": None}}
            elif has_now and had_before:
                refreshed_count += 1
                patches[key] = {"raw": {"deed_chain": li.raw["deed_chain"]}}
        if not patches or args.dry_run:
            return
        with board_lock(REPO, owner="mecklenburg_deed_chain_backfill", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_mecklenburg_deed_chain_batch": len(patches)}, docs_dir=docs_dir)
        print(f"  patch_existing_rows: {pstats}")
        total_patched += pstats.get("applied", 0)

    print(f"pass 2: streaming board, scoped to state={want_state or 'any'} "
          f"county={want_county or 'any'}...")
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        total_rows += 1
        st = (rec.get("state") or "").strip().upper()
        co = (rec.get("county") or "").strip()
        if want_state and st != want_state:
            continue
        if want_county and co != want_county:
            continue
        in_scope_rows += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        had_before = bool(raw.get("deed_chain"))
        if had_before:
            before_count += 1
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            key = None
        batch.append((key, li, had_before))
        if len(batch) >= args.batch_size:
            print(f"  batch at in-scope row {in_scope_rows:,} (board row {total_rows:,})...")
            flush(batch)
            batch = []
    flush(batch)

    print(f"\n=== RESULTS (state={want_state or 'any'} county={want_county or 'any'}) ===")
    print(f"board rows scanned (whole board, pass 2): {total_rows:,}")
    print(f"in-scope rows: {in_scope_rows:,}")
    print(f"  with deed_chain before: {before_count:,}")
    print(f"  with deed_chain after:  {after_count:,} (net {after_count - before_count:+,})")
    print(f"    newly stamped: {new_count:,}")
    print(f"    refreshed (already had one, re-patched with current data): {refreshed_count:,}")
    print(f"    cleared (stale/fallback-contaminated, no genuine records this pass): "
          f"{cleared_count:,}")
    print(f"  no usable dedupe_key (skipped, never guessed at): {collisions:,}")
    if args.dry_run:
        print("\nDRY RUN -- enrich_deed_chain() WAS called (pure/offline, no network; this is a "
              "real logic+yield measurement, not just an eligibility count) -- patch_existing_rows "
              "was NOT called. Nothing written.")
    else:
        print(f"\ntotal rows patched: {total_patched:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
