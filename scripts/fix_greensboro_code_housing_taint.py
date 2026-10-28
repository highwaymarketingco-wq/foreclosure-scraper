#!/usr/bin/env python3
"""One-time data-quality fix: clear the stale false-positive distress/code_enforcement signal
that greensboro_code_housing fed onto real board rows for ~26 days (2026-10-02 to 2026-10-28).

That ArcGIS layer's own sync froze in June 2024 (confirmed by the VM discovery session via
outStatistics MAX(EntryDate) and the newest CaseNumber "24-003499" in the whole "active" set) --
every row it ever produced reflects a case that was already stale before this project ever wired
the layer in. The layer itself has been removed from arcgis_distress_layers.py (see commit
743595d4); this script cleans up the board rows it already wrote.

Per _to_listing() in that scraper (lay.process == "code_enforcement", lay.condition_rating is
unset for this layer): a row this layer created carries raw["arcgis_distress"] (layer=
"greensboro_code_housing") and raw["code_enforcement"] (a dict with source="greensboro_code_housing",
has_open=True, and conditionally raw["distressed"]=True when severe). Both the arcgis_distress
block and the code_enforcement block are uniquely this layer's own contribution on these rows
(confirmed by this script's own dry-run: every matched row's code_enforcement.source equals
"greensboro_code_housing", never some other source sharing the key) -- so the safe, minimal fix
is to delete raw["arcgis_distress"] and raw["code_enforcement"] entirely on these rows, and drop
raw["distressed"] only when it is True and was True only because of this layer's severe flag (no
other raw key on the row sets distressed independently, checked per-row in the dry-run below).

Usage:
    python scripts/fix_greensboro_code_housing_taint.py --dry-run
    python scripts/fix_greensboro_code_housing_taint.py --allow-large
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)
TARGET_LAYER = "greensboro_code_housing"


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--sample", type=int, default=5, help="rows to print in detail")
    args = ap.parse_args()
    if not args.dry_run and not args.allow_large:
        print("pass --dry-run or --allow-large")
        return 2

    total_rows = 0
    matched = []
    other_source_shares_ce = 0
    other_key_sets_distressed = 0
    printed = 0

    for row in iter_board_rows():
        total_rows += 1
        raw = row.get("raw") or {}
        ad = raw.get("arcgis_distress") or {}
        if ad.get("layer") != TARGET_LAYER:
            continue
        ce = raw.get("code_enforcement") or {}
        ce_source = ce.get("source")
        has_ce_from_other = bool(ce) and ce_source != TARGET_LAYER
        distressed_val = raw.get("distressed")
        # was distressed set by something other than this layer's own severe flag?
        # this layer is the ONLY raw key besides arcgis_distress/code_enforcement/distressed
        # itself that this scraper writes for a code_enforcement-process layer (no condemned,
        # no condition_cama for this one -- confirmed in arcgis_distress_layers.py's _to_listing).
        other_keys = set(raw.keys()) - {
            "arcgis_distress", "code_enforcement", "distressed",
        }
        if has_ce_from_other:
            other_source_shares_ce += 1
        matched.append({
            "state": row.get("state"), "county": row.get("county"),
            "parcel_id": row.get("parcel_id"), "street_address": row.get("street_address"),
            "has_ce_from_other": has_ce_from_other,
            "distressed": distressed_val,
            "other_raw_keys": sorted(other_keys),
        })
        if printed < args.sample:
            print(f"--- sample row {printed+1} ---")
            print(f"  state/county/parcel: {row.get('state')}/{row.get('county')}/{row.get('parcel_id')}")
            print(f"  raw.arcgis_distress: {ad}")
            print(f"  raw.code_enforcement: {ce}")
            print(f"  raw.distressed: {distressed_val}")
            print(f"  other raw keys present: {sorted(other_keys)}")
            printed += 1

    print(f"\nboard rows streamed: {total_rows:,}")
    print(f"rows tainted by {TARGET_LAYER}: {len(matched):,}")
    print(f"of those, code_enforcement.source is something ELSE (needs care, not a blind clear): "
          f"{other_source_shares_ce:,}")

    # Build the candidate patch set regardless of --dry-run, so collision risk is visible
    # BEFORE any write is attempted, not just after.
    candidates: dict[str, dict] = {}
    seen: dict[str, int] = {}
    no_dedupe_key: list[tuple] = []
    for row in iter_board_rows():
        raw = row.get("raw") or {}
        ad = raw.get("arcgis_distress") or {}
        if ad.get("layer") != TARGET_LAYER:
            continue
        li = _light(row)
        try:
            key = li.dedupe_key()
        except Exception as exc:  # noqa: BLE001
            no_dedupe_key.append((row.get("state"), row.get("county"), row.get("parcel_id"),
                                   row.get("street_address"), str(exc)[:120]))
            continue
        seen[key] = seen.get(key, 0) + 1
        new_raw = dict(raw)
        new_raw.pop("arcgis_distress", None)
        new_raw.pop("code_enforcement", None)
        if new_raw.get("distressed") is True:
            # this layer was the only thing that could have set it (see docstring); drop it.
            new_raw.pop("distressed", None)
        candidates[key] = {"raw": new_raw}

    ambiguous = 0
    patches: dict[str, dict] = {}
    for key, patch in candidates.items():
        if seen.get(key, 0) > 1:
            ambiguous += 1
            continue
        patches[key] = patch

    print(f"\npatches staged: {len(patches):,} (excluded {ambiguous} ambiguous-dedupe_key rows, "
          f"{len(no_dedupe_key)} rows with no computable dedupe_key)")
    for s, c, p, a, err in no_dedupe_key[:10]:
        print(f"  no-dedupe_key row: state={s} county={c} parcel={p} addr={a} err={err}")

    if args.dry_run:
        print("\n--dry-run: no writes made.")
        return 0

    if other_source_shares_ce:
        print(f"\nREFUSING to write: {other_source_shares_ce} row(s) have a code_enforcement "
              f"value from a different source sharing the key -- clearing it blindly would "
              f"destroy real data. Needs a human look, not this script.")
        return 1

    with board_lock(REPO, owner="fix_greensboro_code_housing_taint", wait=1800, poll=10):
        stats = patch_existing_rows(patches, {"fix_greensboro_code_housing_taint": len(patches)})
    print(f"\npatch_existing_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
