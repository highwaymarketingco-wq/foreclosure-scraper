#!/usr/bin/env python3
"""Backfill `raw.comps` / `raw.comps_tight` (gap_matrix columns) board-wide, SAFELY.

WHY THIS WAS REWRITTEN (2026-11-11). The original version of this script called
`load_board()` (full-board materialization) unconditionally, then `write_artifact()`
over the whole result, with `board_lock()` held across BOTH the board load AND the
live HomeHarvest network fetch (up to 146 county pools) AND the write. Two real,
confirmed-live bugs, not assumptions:

  1. `docs/listings.json` is now 4,847 MB -- 4x past `BOARD_LOAD_MAX_SOURCE_MB`'s
     1,200 MB ceiling (web_artifact.py's own Mac-calibrated guard, set after a prior
     26.3 GB OOM). `load_board()` raises `BoardLoadTooLarge` before doing ANY work.
     This script could not have completed a single run in a long time -- confirmed by
     `docs/HANDOFF.md`'s own Tier-3 "dead, not in any launchd/wrapper" classification,
     zero `backfill_comps`-tagged log lines in `logs/` in the last 30 days, and
     Mecklenburg/Wake (the two biggest NC counties) sitting at 0.0%-0.7% comps/
     comps_tight coverage on the live board despite the comps ENGINE being fully
     built, tested, and wired into main.py (6 call sites) since 2026-10-03.
  2. Holding `board_lock()` across the live network phase is exactly the anti-pattern
     `backfill_mecklenburg_tax.py` was just fixed for tonight (commit 8fc2c4f):
     an 11+ minute lock hold starving every other board-writer. This script's old
     version would have held the lock even longer (up to ~146 HomeHarvest county
     fetches, each 5-30s, serialized via a 6-worker pool -- 5-15+ minutes just for
     pool-building, before a single row is matched).

LIVE-VERIFIED the data source is healthy (2026-11-11, isolated probe, no board I/O):
HomeHarvest's free Realtor.com sold-pool fetch returned Mecklenburg NC 9,517 sold/180d,
Wake NC 9,950, Rutherford NC 763 -- real addresses/prices/sqft/beds/dates. The comps
ENGINE (`enrichment_comps.enrich_with_comps`, strict kind+geo+zip+sqft+beds+era
matching) is not the gap. The gap was purely "the one script that could clear the
historical backlog has been unable to even start since the board passed ~1.2 GB."

THE FIX, mirroring `backfill_mecklenburg_tax.py`'s now-standard pattern:
  - Board I/O is STREAMED (`board_stream.iter_board_rows_with_detail(keys=("comps",))`),
    never `load_board()`. Only rows matching `--counties` (if given) are kept as
    in-memory `Listing.model_construct()` objects -- every other row is discarded as
    it streams past, so memory is bounded by the TARGET counties' row count, not the
    board's 477k+.
  - Candidates are rows with no `raw.comps` yet (the actual backlog), capped at
    `--max-rows` so a single invocation stays small and predictable; re-invoke (or
    loop) to keep grinding through a county's backlog or move to the next county.
  - `enrich_with_comps()` -- the live network + matching phase -- runs with NO LOCK
    held (pure in-memory Listing mutation + HTTP, zero board-file interaction).
  - `board_lock()` wraps ONLY the final `patch_existing_rows()` write, same
    dedupe_key()-collision guard every sibling backfill in this project uses.

Cost model unchanged from the original docstring: bounded by DISTINCT COUNTY COUNT
among the candidates actually selected (one HomeHarvest sold+rent+active fetch per
county, reused in-memory for every candidate row in that county), not row count --
so `--counties` with a short list is cheap even if `--max-rows` is generous.

    python scripts/backfill_comps.py --dry-run --counties "Mecklenburg:NC"
    python scripts/backfill_comps.py --counties "Mecklenburg:NC" --max-rows 500
    python scripts/backfill_comps.py --counties "Mecklenburg:NC,Wake:NC,Buncombe:NC" --max-rows 3000
    python scripts/backfill_comps.py --max-rows 2000   # no county filter: sweep board order
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows_with_detail  # noqa: E402
from foreclosure_scraper.enrichment_comps import enrich_with_comps  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows  # noqa: E402

# Every Listing field enrich_with_comps()/its helpers read or write. Wider than
# backfill_mecklenburg_tax.py's _LIGHT_FIELDS because the comp matcher gates on
# kind/geo/zip/sqft/beds/year/value/land-use, not just identity -- see
# enrichment_comps.py's _classify_kind, _pick_3_comps, _condition_tier,
# _backfill_property_data for the exact reads. Confirmed present on Listing
# (43-field model) before use.
_LIGHT_FIELDS = (
    "state", "county", "parcel_id", "street_address", "zip_code", "case_number",
    "source_url", "listing_type", "city", "latitude", "longitude", "property_kind",
    "living_sqft", "bedrooms", "bathrooms", "year_built", "lot_size_sqft", "acreage",
    "market_value", "tax_value", "land_use", "description", "source", "raw",
)
# raw sub-keys enrich_with_comps can set/clear -- diffed before/after per row.
_RAW_WATCH_KEYS = (
    "comps", "comps_note", "comps_geo_warning", "comp_median_ppsf",
    "rent_comps", "rent_median_ppsf", "estimated_monthly_rent",
    "condition_tier", "market_velocity",
)
# top-level scalar fields _backfill_property_data() can fill (only when currently
# None -- never clears an existing value).
_SCALAR_WATCH_FIELDS = ("living_sqft", "bedrooms", "bathrooms", "year_built", "lot_size_sqft")


def _dedupe_key(li: Listing) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _parse_counties(spec: str) -> set[tuple[str, str]]:
    """'Mecklenburg:NC,Wake:NC' -> {('NC','Mecklenburg'), ('NC','Wake')}."""
    out: set[tuple[str, str]] = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" not in tok:
            raise ValueError(f"--counties token missing ':STATE' -- got {tok!r}")
        name, state = tok.rsplit(":", 1)
        out.add((state.strip().upper(), name.strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--counties", default="",
                     help="comma list of 'County:ST' to scope this batch to (e.g. "
                          "'Mecklenburg:NC,Wake:NC'). Omit to sweep in board order "
                          "across every county, bounded by --max-rows.")
    ap.add_argument("--max-rows", type=int, default=2000,
                     help="cap on candidate rows (no raw.comps yet) loaded into memory "
                          "this invocation. Keep small for a first trial; re-invoke "
                          "(or loop) to keep grinding a county's backlog.")
    args = ap.parse_args()

    docs = REPO / "docs"
    want_counties = _parse_counties(args.counties) if args.counties else None

    # BOARD I/O (streamed, read-only) happens ONLY here, before any lock is needed --
    # discarded rows never become Listing objects. "comps" is the one lazy-detail key
    # we need merged in, to know which rows are genuinely missing it.
    candidates: list[Listing] = []
    keys: list[Optional[str]] = []
    before: list[dict] = []
    scanned = 0
    for rec in iter_board_rows_with_detail(docs / "listings.json.gz", keys=("comps",)):
        scanned += 1
        if len(candidates) >= args.max_rows:
            break
        if want_counties is not None:
            pair = ((rec.get("state") or "").strip().upper(), (rec.get("county") or "").strip())
            if pair not in want_counties:
                continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if raw.get("comps"):
            continue  # already has comps -- not the backlog this script targets
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        candidates.append(li)
        keys.append(_dedupe_key(li))
        raw = li.raw if isinstance(li.raw, dict) else {}
        snap = {k: raw.get(k) for k in _RAW_WATCH_KEYS}
        for f in _SCALAR_WATCH_FIELDS:
            snap[f] = getattr(li, f, None)
        before.append(copy.deepcopy(snap))

    key_counts: dict[str, int] = {}
    for k in keys:
        if k is not None:
            key_counts[k] = key_counts.get(k, 0) + 1

    print(f"scanned: {scanned:,} board rows"
          + (f" (filtered to {sorted(want_counties)})" if want_counties else " (no county filter)"))
    print(f"candidates (no raw.comps yet, within --max-rows {args.max_rows:,}): {len(candidates):,}")
    if not candidates:
        print("nothing to do.")
        return 0

    counties_touched = sorted({(li.state or "", li.county or "") for li in candidates})
    print(f"counties touched this batch: {len(counties_touched)} -> {counties_touched[:10]}"
          + (" ..." if len(counties_touched) > 10 else ""))

    # THE LIVE PHASE -- network (HomeHarvest pool fetches) + matching. No board_lock
    # held: zero board-file interaction happens in here, only in-memory Listing
    # mutation. This is the part the old version wrongly ran under the lock.
    stats = asyncio.run(enrich_with_comps(candidates))
    print(f"\nenrich_with_comps: {stats}")

    if args.dry_run:
        matched_sold = sum(1 for li in candidates if isinstance(li.raw, dict) and li.raw.get("comps"))
        print(f"\n--dry-run: nothing written (live network queries above still ran -- "
              f"{matched_sold:,}/{len(candidates):,} candidates matched at least one comp; "
              f"--dry-run here only skips the board write)")
        return 0

    patches: dict[str, dict] = {}
    collisions = 0
    for li, key, b4 in zip(candidates, keys, before):
        raw = li.raw if isinstance(li.raw, dict) else {}
        after_raw = {k: raw.get(k) for k in _RAW_WATCH_KEYS}
        after_scalar = {f: getattr(li, f, None) for f in _SCALAR_WATCH_FIELDS}
        raw_changed = {k: v for k, v in after_raw.items() if v != b4.get(k)}
        scalar_changed = {f: v for f, v in after_scalar.items()
                          if v is not None and v != b4.get(f)}
        if not raw_changed and not scalar_changed:
            continue
        if key is None:
            continue
        if key_counts.get(key, 0) > 1:
            collisions += 1
            continue
        update: dict = dict(scalar_changed)
        if raw_changed:
            update["raw"] = raw_changed
        patches[key] = update

    print(f"patches staged: {len(patches):,} (dropped as dedupe_key collisions: {collisions:,})")

    if not patches:
        print("no changes to write.")
        return 0

    # THE LOCK, narrowed to just this write. patch_existing_rows() self-enforces
    # require_board_lock() regardless, so this is belt-and-suspenders, not the only
    # thing standing between this script and a lock-less write.
    try:
        with board_lock(REPO, owner="backfill_comps", wait=3600, poll=10):
            result = patch_existing_rows(
                patches, {"backfill_comps": f"n={len(patches)}, counties={len(counties_touched)}"},
                docs_dir=docs)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches from this invocation's "
              f"live queries are lost; re-run to redo them and retry).")
        return 1
    print(f"patch_existing_rows: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
