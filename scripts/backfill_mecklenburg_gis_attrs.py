#!/usr/bin/env python3
"""One-time catch-up for enrichment_gis_attrs.py against Mecklenburg.

FOUND 2026-10-23: investigating atty_legal_description (335,515 est_affected board-wide,
Mecklenburg at 1.92%), traced the real producer -- gap_matrix's own next_action text just
says "existing enrichers", no specific module named. enrichment_gis_attrs.py is the real
producer (writes raw['gis_attrs_full'], which gap_matrix's _LEGAL_KEYS regex reads). Checked
directly: of 39,861 Mecklenburg rows, raw['gis']['queried'] is set on ZERO of them -- this
enricher has NEVER run against a single Mecklenburg row, despite being wired into main.py's
regular run() (line 1975-1977) and merge_today_sources.py. The 1,001 rows that DO carry
gis_attrs_full got it from a DIFFERENT path (parcel_cache_join), and of those, 604 (60.3%)
already have a real txt_legaldesc value -- strong evidence this is a dormant-producer
coverage gap, not a data-availability ceiling like deed_chain turned out to be.

Scoped to ONE county (not the whole 280K-472K-row board) specifically because
enrich_gis_attrs() is too complex to safely trim raw keys for (parcel_cache lookups,
owner_freshness staleness checks, a live-GIS-query fallback, several raw sub-keys
(gis.owner/mailing/last_sale/queried/source, gis_attrs, gis_attrs_full) plus several
top-level Listing fields (assessed_value, market_value, tax_value, living_sqft, year_built,
acreage, land_use, owner_name, street_address)) -- a full-raw-dict load of just Mecklenburg's
39,861 rows is a bounded, measured-safe population, unlike a board-wide full-raw-dict load.

    python scripts/backfill_mecklenburg_gis_attrs.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_mecklenburg_gis_attrs.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

COUNTY = "Mecklenburg"
_TOP_FIELDS = ("assessed_value", "market_value", "tax_value", "living_sqft",
               "year_built", "acreage", "land_use", "owner_name", "street_address")
_RAW_WATCH_KEYS = ("gis", "gis_attrs", "gis_attrs_full")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="process at most this many never-queried rows this run "
                         "(0 = all); lets a long run be chunked into safe, "
                         "independently-patched batches")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print(f"streaming board for {COUNTY} rows (full raw, county-scoped)...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    never_queried_count = 0
    already_queried_skipped = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != COUNTY:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        never_queried = not (raw.get("gis") or {}).get("queried")
        if args.max_rows and never_queried:
            if never_queried_count >= args.max_rows:
                already_queried_skipped += 1
                continue
            never_queried_count += 1
        li = Listing.model_validate(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = {**{f: getattr(li, f, None) for f in _TOP_FIELDS},
                       **{k: li.raw.get(k) if isinstance(li.raw, dict) else None
                          for k in _RAW_WATCH_KEYS}}

    print(f"{COUNTY} rows loaded this run: {len(keyed):,}"
          + (f" (capped at {args.max_rows} never-queried, {already_queried_skipped} "
             f"more never-queried rows left for a future batch)" if args.max_rows else ""))
    print("running enrich_gis_attrs()...")

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
        for key, p in list(patches.items())[:3]:
            print("  ", key, {k: v for k, v in p.items() if k != "raw"},
                  "raw_keys_changed=", list(p.get("raw", {}).keys()))
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_mecklenburg_gis_attrs", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_mecklenburg_gis_attrs": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
