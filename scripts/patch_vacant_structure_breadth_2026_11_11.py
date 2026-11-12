#!/usr/bin/env python3
"""Backfill raw['gis']['vacant'] onto the board's pre-2026-11-11-fix rows from the five
scraper sources that already had a real, per-row "this structure is vacant" determination
(already flowing into raw['vacancy'] or, for spartanburg_vacant, the bare top-level
raw['vacant'] dict) but never mirrored it into raw['gis']['vacant'] -- the key gap_matrix.py's
"vacant" column actually checks (confirmed by reading gap_matrix.py's own _cohort_flags
comment). Same bug class, same fix shape as scripts/patch_charlotte_condemned_vacancy.py's
2026-10-20 fix for charlotte_open_data.py's fof_ordered branch; this is the breadth pass for
the five other real producers found 2026-11-11 (see each source module's own new comment and
gap_matrix.py's "vacant" Spec producers tuple for the live-verified evidence per source):

    counties_nc.gastonia_code_enforcement                         (Gaston NC)
    counties_generic.arcgis_distress.kinston_proposed_demolition   (Lenoir NC)
    counties_generic.arcgis_distress.rocky_mount_blight_survey_2025 (Nash/Edgecombe NC)
    counties_sc.spartanburg_vacant                                 (Spartanburg SC)
    counties_generic.arcgis_distress.columbia_code_vacant_boarded  (Richland SC)
    counties_generic.arcgis_distress.rockhill_code_demolition      (York SC)

Read-only scan first (--dry-run). The lock (board_lock) wraps ONLY the patch_existing_rows()
write, never the board scan above it -- the live board is iterated with no lock held, exactly
the shape the 2026-11-11 session's own mandate requires (a wide lock around the whole pass,
including any read/compute step, is the bug that stalled other writers on
backfill_mecklenburg_tax.py the same night; this script never does a live network query at
all, since every value it needs is already sitting in the board's own raw dict).

    python scripts/patch_vacant_structure_breadth_2026_11_11.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/patch_vacant_structure_breadth_2026_11_11.py --allow-large
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

# source slug -> True means "every EXISTING board row from this source is vacant by
# construction, patch unconditionally". Two different reasons land a source here:
# (1) spartanburg_vacant's own layer scope is the city's vacant-property registry, so every
#     row it ever wrote is vacant by construction (confirmed by reading the module).
# (2) columbia_code_vacant_boarded / rockhill_code_demolition: their Layer.vacancy=True opt-in
#     IS the 2026-11-11 fix -- no code before today ever wrote raw['vacancy'] for these two, so
#     an EXISTING board row from either can never carry the gated marker checked below; every
#     row already on the board from them was already filtered vacant/boarded/demolition at
#     fetch time (the where= clause, or the dedicated demolition sub-layer) and qualifies.
# False means "patch only rows whose raw already carries a real per-row vacant=True
# determination" -- the three NC sources whose per-row vacancy condition predates today's
# fix (only the gis.vacant MIRROR is new), so an existing qualifying row already carries the
# raw['vacancy'] wrapper the unchanged, older half of that same code wrote.
_SOURCES_UNCONDITIONAL = {
    "counties_sc.spartanburg_vacant",
    "counties_generic.arcgis_distress.columbia_code_vacant_boarded",
    "counties_generic.arcgis_distress.rockhill_code_demolition",
}
_SOURCES_GATED = {
    "counties_nc.gastonia_code_enforcement",
    "counties_generic.arcgis_distress.kinston_proposed_demolition",
    "counties_generic.arcgis_distress.rocky_mount_blight_survey_2025",
}
_ALL_SOURCES = _SOURCES_UNCONDITIONAL | _SOURCES_GATED


def _already_vacant_per_row(raw: dict) -> bool:
    """True when this row's OWN raw data already shows a real, per-row vacant
    determination -- i.e. the live scraper, if re-run today, would set raw['gis']['vacant']
    for this exact row under the 2026-11-11 fix. Mirrors raw['vacancy']['vacant'], the key
    every one of the five gated sources already writes in the identical branch as the new
    gis.vacant line (confirmed by reading each source file)."""
    vc = raw.get("vacancy")
    return isinstance(vc, dict) and vc.get("vacant") is True


def main() -> int:
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

    patches: dict[str, dict] = {}
    by_county: dict[tuple[str, str], int] = {}
    skipped_no_signal = 0
    skipped_already_has = 0

    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        source = rec.get("source")
        if source not in _ALL_SOURCES:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
        if gis.get("vacant"):
            skipped_already_has += 1
            continue
        if source not in _SOURCES_UNCONDITIONAL and not _already_vacant_per_row(raw):
            skipped_no_signal += 1
            continue

        light = Listing.model_construct(**{
            k: rec.get(k) for k in
            ("state", "county", "parcel_id", "street_address", "zip_code",
             "case_number", "source_url", "listing_type")})
        try:
            key = light.dedupe_key()
        except Exception:  # noqa: BLE001
            continue

        patch_raw: dict = {"gis": {**gis, "vacant": True}}
        if not isinstance(raw.get("vacancy"), dict):
            # spartanburg_vacant's old rows: the legacy top-level raw['vacant'] dict exists
            # but never the raw['vacancy'] wrapper distress_score's PROPERTY signal reads --
            # add it too, additive only (never overwrites the legacy key).
            patch_raw["vacancy"] = {"vacant": True, "boarded_up": None, "utility_status": None,
                                    "source": source}
        patches[key] = {"raw": patch_raw}
        ck = (rec.get("state"), rec.get("county"))
        by_county[ck] = by_county.get(ck, 0) + 1

    print(f"rows to patch: {len(patches)}")
    print(f"  (skipped, already has gis.vacant: {skipped_already_has})")
    print(f"  (skipped, no per-row vacant signal yet on this source: {skipped_no_signal})")
    for ck, n in sorted(by_county.items(), key=lambda x: -x[1]):
        print(f"  {ck}: {n}")

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="patch_vacant_structure_breadth_2026_11_11", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"patch_vacant_structure_breadth_2026_11_11": len(patches)}, docs_dir=docs_dir)
        print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
