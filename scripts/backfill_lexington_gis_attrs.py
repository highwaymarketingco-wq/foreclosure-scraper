#!/usr/bin/env python3
"""Lexington SC-scoped catch-up for enrichment_gis_attrs.py.

WHY THIS EXISTS. gap_matrix.py (2026-11-16 run) flagged Lexington SC's `beds_baths`
column as the single biggest 'sourced-not-built' item on the whole board: 30,528
estimated affected rows, 0% filled, source "tax/property card:
lexingtoncountytreasurer.qpaybill.com".

Investigation (2026-11-15/16) found that attribution misleading and the gap itself
NOT a missing-reader problem:

  * lexingtoncountytreasurer.qpaybill.com (gap_matrix's named source) is free/open, not
    walled -- confirmed live (GET+POST the real search grid, no CAPTCHA/WAF markers) --
    but its tax/property-card detail page genuinely carries no bedroom/bathroom field
    anywhere (verified against 4 live Lexington parcels, including the page's hidden
    "Assessor Info" panel, whose labels render with no values at all). The probate
    column's SEPARATE "walled (CAPTCHA)" classification is for a DIFFERENT host
    entirely (www.lex-co.com/ProbateSearch/estates, an Angular app behind a reCAPTCHA
    disclaimer) -- not the same wall, not even the same family (gap_matrix.py's own
    source_status() resolves beds_baths via the "tax" block and probate via a separate
    "probate" block in county_records_matrix.json). Building a beds_baths reader
    against qpaybill would not hit a wall; it would just read a page with no such data.

  * The REAL, already-free source is maps.lex-co.com's ArcGIS parcel layer
    (Property/MapServer/4) -- live-confirmed to publish Nbr_Bedroom, Nbr_FullBath,
    Nbr_HalfBath, YearBuilt, Stories, SqftLA directly (e.g. TMS 005200-04-076: 3 bed /
    2 full+1 half bath / 2152 sqft / built 1997). This layer is NOT new: parcel_cache.py
    already has it configured (PARCEL_LAYERS["Lexington"]), already merges that exact
    field mapping in via FACT_MAPS["Lexington"] (added 2026-10-07), and
    data/parcel_cache/lexington.sqlite -- refreshed today -- already holds real
    bedrooms/bathrooms/year_built/stories for 102,205 of its 147,066 cached parcels.
    parcel_cache_join.py's apply_hit() already writes hit["bedrooms"]/["bathrooms"]
    onto li.bedrooms/li.bathrooms, fill-only.

  * So every piece already exists and already works. What is missing is simply that
    enrichment_gis_attrs.py (the function that joins this cache onto EXISTING board
    rows -- see project_gis_attrs_boardwide_dormant_2026-10-23) has not yet reached
    Lexington's ~31,402 rows in its slow, file-order, board-wide backlog sweep
    (scripts/backfill_gis_attrs_boardwide.py). That script has no per-county scope, so
    there is no way to target Lexington specifically through it. This script is that
    scope -- the same Mecklenburg-scoped-then-generalized pattern this codebase already
    used once (backfill_mecklenburg_gis_attrs.py came first; backfill_gis_attrs_boardwide.py
    generalized it). It reuses enrich_gis_attrs()/patch_existing_rows()/board_lock()
    verbatim; the only addition is a state=='SC' and county=='Lexington' filter on the
    candidate pool, so every row this run processes actually counts toward Lexington's
    own backlog instead of whatever county happens to sit first in file order.

SAFETY. Same guarantees as backfill_gis_attrs_boardwide.py: patch_existing_rows only
(never load_board()/write_artifact()), trimmed raw keys (board-scale memory safety),
deepcopy'd before/after raw-dict snapshots (enrich_gis_attrs mutates raw['gis'] in
place), the GLOBAL shared-fallback-point pre-pass kept board-wide (a Lexington row's
lat/lng can coincide with a point shared by OTHER counties' rows, so this check cannot
be county-scoped without losing correctness), and board_lock() with a real wait/poll
(never forces past a held lock).

    python scripts/backfill_lexington_gis_attrs.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_lexington_gis_attrs.py --allow-large --max-rows 5000
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.block_binding import FALLBACK_POINT_MIN_ROWS  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, BoardLockBusy, board_lock, board_patch_size_state, patch_existing_rows,
)

STATE, COUNTY = "SC", "Lexington"

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "latitude", "longitude", "owner_name",
                                      "market_value", "tax_value", "living_sqft",
                                      "year_built", "acreage", "assessed_value",
                                      "land_use")
_TOP_FIELDS = ("assessed_value", "market_value", "tax_value", "living_sqft",
               "year_built", "acreage", "land_use", "owner_name", "street_address",
               # 2026-11-15: bedrooms/bathrooms were missing here even though
               # parcel_cache_join.apply_hit() sets li.bedrooms/li.bathrooms (real top-level
               # Listing scalars, models.py) whenever a cache hit carries them -- this is the
               # SAME omission as scripts/backfill_gis_attrs_boardwide.py's own _TOP_FIELDS
               # (fixed there too). Without this, every prior board-wide batch computed real
               # bedroom/bathroom fills in memory (visible in enrich_gis_attrs's own "filled
               # bedrooms"/"filled bathrooms" stats) and then silently DROPPED them from the
               # patch sent to patch_existing_rows -- live-confirmed on Lexington SC: a dry
               # run showed cache_join="filled bedrooms": 25,609 while the resulting patch
               # carried zero bedroom changes, and the published board independently showed
               # 0 of 31,402 Lexington rows with bedrooms/bathrooms set despite this backfill
               # having "landed" 10+ batches board-wide already (see
               # project_gis_attrs_boardwide_dormant_2026-10-23). (`stories` is NOT part of
               # this bug: apply_hit() writes it into raw['gis']['stories'], not a Listing
               # attribute, and raw['gis'] is already covered by _RAW_WATCH_KEYS below.)
               "bedrooms", "bathrooms")
_RAW_WATCH_KEYS = ("gis", "gis_attrs", "gis_attrs_full", "owner_name_as_of")
_NEEDED_RAW_KEYS = ("gis", "gis_attrs", "gis_attrs_full", "owner_name_as_of",
                    "geo_imprecise", "geocoded_by_name", "parcel_id_nulled",
                    "parcel_id_alias")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-rows", type=int, default=0,
                     help="process at most this many never-queried Lexington SC rows "
                          "this run (0 = all ~30k candidates in one pass)")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("pass 1: finding globally-shared fallback points (lat,lng only, board-wide, "
          "cheap) -- kept board-wide on purpose, see module docstring...")
    point_counts: Counter = Counter()
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        lat, lng = rec.get("latitude"), rec.get("longitude")
        try:
            point_counts[(round(float(lat), 5), round(float(lng), 5))] += 1
        except (TypeError, ValueError):
            continue
    shared_points = {p for p, c in point_counts.items() if c >= FALLBACK_POINT_MIN_ROWS}
    print(f"  {len(shared_points):,} points shared by >={FALLBACK_POINT_MIN_ROWS} rows board-wide")

    print(f"pass 2: streaming board, filtered to {STATE}/{COUNTY} only...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    never_queried_count = 0
    already_queried_skipped = 0
    structurally_unresolvable = 0
    not_lexington = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("state") or "") != STATE or (rec.get("county") or "") != COUNTY:
            not_lexington += 1
            continue
        full_raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        never_queried = not (full_raw.get("gis") or {}).get("queried")
        if not never_queried:
            continue
        if not (rec.get("parcel_id") or (rec.get("latitude") and rec.get("longitude"))):
            # Same structural exclusion as backfill_gis_attrs_boardwide.py: enrich_gis_attrs()
            # needs a parcel_id OR lat/lng to do anything; a row with neither will never
            # reach the 'queried' stamp via this function.
            structurally_unresolvable += 1
            continue
        if not rec.get("parcel_id"):
            try:
                pt = (round(float(rec.get("latitude")), 5), round(float(rec.get("longitude")), 5))
            except (TypeError, ValueError):
                pt = None
            if pt in shared_points:
                structurally_unresolvable += 1
                continue
        if args.max_rows and never_queried_count >= args.max_rows:
            already_queried_skipped += 1
            continue
        never_queried_count += 1
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = {k: full_raw[k] for k in _NEEDED_RAW_KEYS if k in full_raw}
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        # deepcopy: enrich_gis_attrs() mutates raw['gis'] in place when it already exists
        # (li.raw.setdefault("gis", {})["queried"] = True) -- a shallow snapshot would hold
        # the SAME dict object and silently "see" the mutation too (the exact bug
        # project_gis_attrs_boardwide_dormant_2026-10-23 found and fixed board-wide).
        before[key] = {**{f: getattr(li, f, None) for f in _TOP_FIELDS},
                       **{k: copy.deepcopy(li.raw.get(k)) for k in _RAW_WATCH_KEYS}}

    print(f"{COUNTY} {STATE} rows seen: {never_queried_count + already_queried_skipped:,} "
          f"never-queried-and-resolvable "
          f"({already_queried_skipped:,} left for a future batch if --max-rows capped it, "
          f"{structurally_unresolvable:,} structurally unresolvable -- no parcel_id and no "
          f"usable lat/lng, this function can never act on them)")
    print(f"rows loaded this run: {len(keyed):,} (scanned past {not_lexington:,} non-Lexington rows)")

    if not keyed:
        print("nothing to do.")
        return 0

    async def run():
        return await enrich_gis_attrs(list(keyed.values()))

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        after = {**{f: getattr(li, f, None) for f in _TOP_FIELDS},
                 **{k: li.raw.get(k) if isinstance(li.raw, dict) else None
                    for k in _RAW_WATCH_KEYS}}
        if after == before[key]:
            continue
        patch: dict = {}
        for f in _TOP_FIELDS:
            if after[f] != before[key][f]:
                patch[f] = after[f]
        raw_patch = {k: after[k] for k in _RAW_WATCH_KEYS if after[k] != before[key][k]}
        if raw_patch:
            patch["raw"] = raw_patch
        if patch:
            patches[key] = patch

    print(f"rows changed: {len(patches):,}")
    beds_gained = sum(1 for p in patches.values()
                      if isinstance(p.get("raw", {}).get("gis_attrs_full"), dict)
                      and any(str(k).lower() in ("nbr_bedroom", "bedrooms")
                              for k in p["raw"]["gis_attrs_full"]))
    print(f"  of those, raw.gis_attrs_full carries a bedroom-shaped key: {beds_gained:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, {k: v for k, v in p.items() if k != "raw"},
                  "raw_keys_changed=", list(p.get("raw", {}).keys()))
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    try:
        with board_lock(REPO, owner="backfill_lexington_gis_attrs", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_lexington_gis_attrs": len(patches)}, docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches from this "
              f"invocation's enrichment pass are lost; re-run to redo them and retry).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
