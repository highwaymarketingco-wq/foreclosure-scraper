#!/usr/bin/env python3
"""BOARD-WIDE catch-up for enrichment_gis_attrs.py.

FOUND 2026-10-23: after landing scripts/backfill_mecklenburg_gis_attrs.py (confirmed
enrich_gis_attrs() had never run against a single Mecklenburg row), checked the WHOLE
board: of 472,777 rows, only 36 carry raw['gis']['queried'] -- the 36 my own Mecklenburg
batches just stamped tonight. This enricher (fills legal_description, assessed_value,
market_value, living_sqft, year_built, acreage, land_use, owner_name, all at once) has
essentially NEVER run against the historical board, for ANY county, despite being wired
into main.py's regular run() (line 1975-1977) and merge_today_sources.py. This is the
single biggest dormant-producer finding of the night.

TRIMMED RAW KEYS, board scale. Unlike backfill_mecklenburg_gis_attrs.py (which safely
loaded one county's full raw dicts -- ~39,861 rows, ~1.2GB), the full board is 472,777
rows; a full-raw-dict load at that scale is the SAME 14-16GB OOM class the shared
run_pending_signal_enrichers.py and the first backfill_incarceration.py attempt both
hit. Traced every raw sub-key enrich_gis_attrs() actually reads/writes (including its
_bag_binds()/tax_binding.row_ids()/block_binding.imprecise_point() dependencies):
  gis, gis_attrs, gis_attrs_full      -- this module's own read/write keys
  owner_name_as_of                    -- owner_freshness staleness stamp
  geo_imprecise, geocoded_by_name     -- block_binding.imprecise_point()'s fallback-point check
  parcel_id_nulled, parcel_id_alias   -- tax_binding.row_ids()'s id-collision guard
Not trimmed: tax_binding.row_ids()'s per-SOURCE alias long-id lookup (_ALIAS_LONG_IDS,
currently only lincoln_vacant) -- omitting it only makes _bag_binds() slightly MORE
lenient on that one source (the function's own designed fallback when ids are
unreadable: "not evidence either way" -> binds=True), never less safe.

PACING. parcel_cache hits are local/free; only rows needing a LIVE query are throttled
by http_client.py's global per-hostname delay (~1.15s/request, confirmed 2026-10-23).
Mecklenburg's ratio (71.5% cache hit, 28.5% live-query) suggests a full board-wide run
would need many hours just for the live-query tail -- --max-rows chunks this into
independently-patched batches, same as the Mecklenburg version.

    python scripts/backfill_gis_attrs_boardwide.py --dry-run --max-rows 3000
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_gis_attrs_boardwide.py --allow-large --max-rows 3000
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
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "latitude", "longitude", "owner_name",
                                      "market_value", "tax_value", "living_sqft",
                                      "year_built", "acreage", "assessed_value",
                                      "land_use")
_TOP_FIELDS = ("assessed_value", "market_value", "tax_value", "living_sqft",
               "year_built", "acreage", "land_use", "owner_name", "street_address")
_RAW_WATCH_KEYS = ("gis", "gis_attrs", "gis_attrs_full", "owner_name_as_of")
_NEEDED_RAW_KEYS = ("gis", "gis_attrs", "gis_attrs_full", "owner_name_as_of",
                    "geo_imprecise", "geocoded_by_name", "parcel_id_nulled",
                    "parcel_id_alias")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="process at most this many never-queried rows this run "
                         "(0 = all); chunks a long run into safe, independently-"
                         "patched batches")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("pass 1: finding globally-shared fallback points (lat,lng only, cheap)...")
    point_counts: Counter = Counter()
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        lat, lng = rec.get("latitude"), rec.get("longitude")
        try:
            point_counts[(round(float(lat), 5), round(float(lng), 5))] += 1
        except (TypeError, ValueError):
            continue
    shared_points = {p for p, c in point_counts.items() if c >= FALLBACK_POINT_MIN_ROWS}
    print(f"  {len(shared_points):,} points shared by >={FALLBACK_POINT_MIN_ROWS} rows "
          f"(same threshold enrich_gis_attrs() itself uses -- a row with no parcel_id "
          f"AT one of these is a fallback/county-seat centroid, not its own location, "
          f"and the function always refuses to live-query it; computed GLOBALLY here "
          f"so a --max-rows batch can skip these ahead of time instead of burning a "
          f"whole batch's cap loading rows the function will just skip anyway)")

    print("pass 2: streaming board (trimmed raw, all counties)...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    never_queried_count = 0
    already_queried_skipped = 0
    structurally_unresolvable = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        full_raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        never_queried = not (full_raw.get("gis") or {}).get("queried")
        if args.max_rows:
            if not never_queried:
                # Already processed by an earlier batch -- nothing left for this
                # function to do here (idempotent skip inside enrich_gis_attrs
                # confirms this; found live 2026-10-23 that omitting this check
                # let already-done rows ride along "for free" each batch,
                # wasting load time without being capped).
                continue
            if not (rec.get("parcel_id") or (rec.get("latitude") and rec.get("longitude"))):
                # enrich_gis_attrs() needs a parcel_id OR lat/lng to do ANYTHING
                # (parcel_cache lookup requires parcel_id; both live-query paths
                # require one or the other) -- a row with neither never reaches
                # the 'queried' stamp and will keep re-appearing as a candidate
                # forever. Found live 2026-10-23: 63,115 of 471,672 never-queried
                # rows are like this (liensnc/nc_ecourts/tax-list filing sources
                # with no property-record geocode) -- batches 4-5 landed on a
                # long contiguous run of them in file order and cratered to
                # near-zero yield. Excluded from the candidate pool entirely
                # rather than just deprioritized, since this function can never
                # act on them.
                structurally_unresolvable += 1
                continue
            if not rec.get("parcel_id"):
                try:
                    pt = (round(float(rec.get("latitude")), 5), round(float(rec.get("longitude")), 5))
                except (TypeError, ValueError):
                    pt = None
                if pt in shared_points:
                    # No parcel_id and this point is shared by >=FALLBACK_POINT_MIN_ROWS
                    # rows board-wide -- a fallback/county-seat centroid, not this row's
                    # own location. enrich_gis_attrs() always refuses to live-query it
                    # (block_binding.imprecise_point() -> skipped_fallback_point, never
                    # reaches the 'queried' stamp). Found live 2026-10-23: batches 4-6
                    # kept landing on a 100K+-row cluster of exactly this shape
                    # (environmental/registry/filing sources sharing a county centroid).
                    structurally_unresolvable += 1
                    continue
            if never_queried_count >= args.max_rows:
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
        # deepcopy the raw-dict values: enrich_gis_attrs() MUTATES raw['gis'] in
        # place (li.raw.setdefault("gis", {})["queried"] = True) when it already
        # exists, rather than replacing it -- a shallow snapshot would hold the
        # SAME dict object, so it would "see" the mutation too and the diff below
        # would wrongly report no change. Found live 2026-10-23: 224,446 of
        # 472,777 rows already carry a raw['gis'] dict from another source, and
        # every one of them was silently falling through this exact trap --
        # their 'queried' stamp (and any gis.owner/mailing fill) never reached
        # the patch, so they looked "never queried" again on the next batch.
        before[key] = {**{f: getattr(li, f, None) for f in _TOP_FIELDS},
                       **{k: copy.deepcopy(li.raw.get(k)) for k in _RAW_WATCH_KEYS}}

    print(f"rows loaded this run: {len(keyed):,}"
          + (f" (capped at {args.max_rows} resolvable never-queried, {already_queried_skipped} "
             f"more left for a future batch, {structurally_unresolvable:,} skipped -- no "
             f"parcel_id and no lat/lng, this function can never act on them)"
             if args.max_rows else ""))

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
    legal_gained = sum(1 for p in patches.values()
                       if isinstance(p.get("raw", {}).get("gis_attrs_full"), dict)
                       and any(str(k).lower().startswith(("legal", "txt_legaldesc"))
                               for k in p["raw"]["gis_attrs_full"]))
    print(f"  of those, gained a gis_attrs_full with a legal-description-shaped key: {legal_gained:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, {k: v for k, v in p.items() if k != "raw"},
                  "raw_keys_changed=", list(p.get("raw", {}).keys()))
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_gis_attrs_boardwide", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_gis_attrs_boardwide": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
