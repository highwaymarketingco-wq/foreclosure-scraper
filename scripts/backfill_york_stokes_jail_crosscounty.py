#!/usr/bin/env python3
"""One-time catch-up: run enrichment_jail_bookings.py's existing, unmodified match_rosters()
(same-county) AND match_cross_county() (cross-county "fugitive heir" fanout) for real against
York SC and Stokes NC's jail rosters -- both wired into ROSTERS 2026-11-16 (round 8) but never
actually run through THIS module's own matcher against the live board.

WHY THIS EXISTS, PRECISELY
    scripts/backfill_jail_rosters.py already exists and already picks up York/Stokes
    automatically (it imports ROSTERS directly), but its --apply path only calls
    match_rosters() -- it never calls match_cross_county(). A live board_stream probe
    2026-11-16 (iter_board_rows(), never load_board()) found:
      - York SC: 150 rows already carry raw['jail_booking'] with county=='York' -- but every
        one of those is the scrapers/national/jail_bookings.py SCRAPER's own inmate-as-lead
        rows (vendor=='jail_bookings_scraper', no matched_name/confidence -- see
        _is_own_same_county_stamp's own docstring), NOT this enrichment module's stamp. THIS
        module's own property-owner name-match against York's roster has never run for real.
      - Stokes NC: zero rows anywhere carry raw['jail_booking'] with county=='Stokes'.
      - Zero rows anywhere (either county) carry raw['jail_booking_new'] (the cross-county
        signal -- the single biggest cell in the whole gap_matrix bucket this fix targeted,
        jail_booking_new for York alone was 80,799 est_rows_affected).
      - A dry-run probe of jail_roster_history (_load_roster(..., dry_run=True), zero side
        effects) confirms baseline=None/health_reason=no_history for BOTH counties right now
        -- this module's own sidecar has never been committed for either, so the one-shot
        is_new_booking window match_cross_county depends on is genuinely still open for both
        (145/150 York, 114/114 Stokes marked is_new_booking=True on today's live fetch).

SCOPE
    Exactly 2 roster entries (the ones ROSTERS added 2026-11-16): (SC, York, york_webforms, ...)
    and (NC, Stokes, citizen_connect, StokesCoNC|). Not a general jail-roster re-run.

HOW (mirrors backfill_jail_rosters.py's / backfill_cchs_lien_sweep.py's own conventions)
    ONE real (non-dry-run unless --dry-run) fetch of each roster via the existing _load_roster
    -- the only chance to observe is_new_booking before the sidecar records a baseline. ONE
    streaming board pass (board_stream.iter_board_rows(), never load_board()) builds:
      (a) lightweight Listing.model_construct() objects for every York SC / Stokes NC row
          (bounded: ~82K rows total, same scale this project already handles for Mecklenburg
          etc in backfill_jail_rosters.py) -- fed to match_rosters(), same-county lane;
      (b) lightweight Listings ONLY for rows elsewhere in SC (for York's roster) or NC (for
          Stokes') whose normalized (last, first) owner-name matches one of the <=259
          is_new_booking==True roster names, pre-filtered DURING the same stream so nothing
          outside that tiny name-set is ever constructed -- fed to match_cross_county(), which
          builds its own owner index from exactly this pre-filtered candidate pool (a York SC
          resident can never cross-match Stokes' NC roster or vice versa: match_cross_county's
          own lookup is scoped to the roster's own state by construction, so no cross-STATE
          pairing between these two counties is possible or attempted here).
    patch_existing_rows() under board_lock(REPO, ...) for the write -- never append_new_rows()
    (nothing here is a new row, only raw field patches on existing ones).

    python scripts/backfill_york_stokes_jail_crosscounty.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_york_stokes_jail_crosscounty.py
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import os
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_jail_bookings import (  # noqa: E402
    ROSTERS, _load_roster, _name_parts, _norm_key, _owner_of,
    match_cross_county, match_rosters,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

TARGET_COUNTIES = {("SC", "York"), ("NC", "Stokes")}
_ROSTER_ENTRIES = [e for e in ROSTERS if (e[0], e[1]) in TARGET_COUNTIES]


def _light(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
    li.owner_name = rec.get("owner_name")
    raw = rec.get("raw")
    li.raw = dict(raw) if isinstance(raw, dict) else {}
    return li


def _scan(docs_dir: Path, wanted_names: dict[str, set[tuple]]) -> tuple[list[Listing], list[Listing]]:
    """ONE streaming pass over the whole board. Returns (same_county, cross_candidates)."""
    same_county: list[Listing] = []
    cross_candidates: list[Listing] = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        state = (rec.get("state") or "").upper()
        county = (rec.get("county") or "").replace(" County", "").strip()
        if (state, county) in TARGET_COUNTIES:
            same_county.append(_light(rec))
            continue
        wanted = wanted_names.get(state)
        if not wanted:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if isinstance(raw.get("jail_booking_new"), dict):
            continue  # already flagged (an earlier/concurrent run) -- never re-touched here
        parts = _name_parts(rec.get("owner_name") or "")
        if not parts:
            continue
        if _norm_key(*parts) in wanted:
            cross_candidates.append(_light(rec))
    return same_county, cross_candidates


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print(f"roster entries: {_ROSTER_ENTRIES}")
    t0 = time.time()
    rosters = dict(await asyncio.gather(
        *[_load_roster(s, c, v, t, dry_run=args.dry_run) for s, c, v, t in _ROSTER_ENTRIES]))
    for (s, c), idx in rosters.items():
        n_new = sum(1 for h in idx.values() if h.get("is_new_booking"))
        print(f"  {s} {c}: roster_size={len(idx)} healthy={getattr(idx, 'healthy', False)} "
              f"is_new_booking=True count={n_new} (fetch took so far "
              f"{round(time.time() - t0, 1)}s)")

    wanted_names: dict[str, set[tuple]] = {}
    for (s, _c), idx in rosters.items():
        wanted_names.setdefault(s, set()).update(
            k for k, hit in idx.items() if hit.get("is_new_booking"))
    print(f"wanted cross-county name-keys: { {s: len(v) for s, v in wanted_names.items()} }")

    print("scanning board once...")
    t1 = time.time()
    same_county, cross_candidates = _scan(docs_dir, wanted_names)
    print(f"board scan done in {round(time.time() - t1, 1)}s: "
          f"same_county={len(same_county):,} rows, "
          f"cross_candidates={len(cross_candidates):,} name-matched rows elsewhere")

    before = {id(li): copy.deepcopy(li.raw) for li in (same_county + cross_candidates)}

    gate_stats: dict = {}
    today = date.today()
    sc_matched = match_rosters(same_county, rosters, today=today, stats=gate_stats)
    cc_matched = match_cross_county(cross_candidates, rosters)

    print(f"\nmatch_rosters (same-county): {len(sc_matched)} newly matched; stats={gate_stats}")
    print(f"match_cross_county: {len(cc_matched)} newly flagged raw['jail_booking_new']")

    all_listings = same_county + cross_candidates
    patches: dict[str, dict] = {}
    for li in all_listings:
        if li.raw != before.get(id(li)):
            try:
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001
                continue
            patches[key] = {"raw": li.raw}

    print(f"\npatches staged: {len(patches)}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    if not patches:
        print("nothing to write.")
        return 0

    with board_lock(REPO, owner="york_stokes_jail_crosscounty_backfill", wait=600, poll=10):
        wstats = patch_existing_rows(
            patches, {"york_stokes_jail_crosscounty_backfill": len(patches)}, docs_dir=docs_dir)
        print("patch_existing_rows:", wstats)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
