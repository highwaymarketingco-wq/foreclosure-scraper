#!/usr/bin/env python3
"""One-time catch-up for enrichment_recorded_comps.py against Carteret NC.

FOUND round 69 (2026-11-19), FIXED round 70 (2026-11-19). Round 69's
recorded_comps audit found Carteret structurally dead for a one-line reason:
`RECORDED_COMP_CONFIG[("NC", "Carteret")]` was already configured correctly
(SALE_PRICE/SaleDate/HtdSqFt, added 2026-08-19), but `enrich()`'s own
`base = COUNTY_GIS.get(f"{state}:{county}", {}).get("url")` was always None
-- `enrichment_owner_mailing.COUNTY_GIS` had NO "NC:Carteret" entry at all,
so the whole county was skipped before any network call, regardless of the
already-correct field config.

Round 70 traced Carteret's working cama_condition layer (enrichment_
cama_condition.py's CAMA_SOURCES, live 95.3% match per round 69) to the exact
same county parcel MapServer that recorded_comps' own config already expects
(SALE_PRICE/SaleDate/HtdSqFt all live-confirmed present on it, 114 fields
total), added a "NC:Carteret" entry to COUNTY_GIS (its `url` is the only
field recorded_comps.enrich() reads from this dict -- the owner/mail/situs/
parcel/out_fields keys are enrichment_owner_mailing.py's own, separate
benefit, not read here), and live-verified the UNCHANGED recorded_comps
module end-to-end before building this script: a 25-point spatial-query
sample (real Carteret lat/lon, same geometry+where+ppsf shape this module
uses) returned 25/25 (100%) with >=3 valid nearby comps -- every sample
subject would get a stamp.

Board census (2026-11-19): candidates are counted by this script's own
streaming pass below (latitude+longitude present, not already tagged
recorded_comps) -- no code change needed in enrichment_recorded_comps.py
itself, only the COUNTY_GIS entry.

Scoped to one county, same shape as backfill_pickens_recorded_comps.py
(this module's prior catch-up, round 69) / backfill_lincoln_tax_relief.py /
backfill_buncombe_tax_relief.py.

    python scripts/backfill_carteret_recorded_comps.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_carteret_recorded_comps.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_recorded_comps import enrich as enrich_recorded_comps  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

COUNTY = "Carteret"
STATE = "NC"
_RAW_WATCH_KEYS = ("recorded_comps", "comp_median_ppsf_recorded")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-sample", type=int, default=0,
                     help="cap candidate rows (0 = no cap, the full county)")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print(f"streaming board for {COUNTY}, {STATE} rows with lat/lon, "
          f"not already tagged recorded_comps...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != COUNTY or (rec.get("state") or "").strip() != STATE:
            continue
        if not rec.get("latitude") or not rec.get("longitude"):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if raw.get("recorded_comps"):
            continue  # already tagged, nothing new to gain
        li = Listing.model_validate(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = {k: copy.deepcopy(li.raw.get(k)) if isinstance(li.raw, dict) else None
                       for k in _RAW_WATCH_KEYS}
        if args.max_sample and len(keyed) >= args.max_sample:
            break

    print(f"candidate rows this run: {len(keyed):,}")
    print("running enrichment_recorded_comps.enrich() (one spatial query/lead, "
          "15-way concurrency, 500m bucket cache)...")

    async def run():
        return await enrich_recorded_comps(list(keyed.values()))

    asyncio.run(run())

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        after = {k: li.raw.get(k) if isinstance(li.raw, dict) else None for k in _RAW_WATCH_KEYS}
        if after == before[key]:
            continue
        raw_patch = {k: after[k] for k in _RAW_WATCH_KEYS if after[k] != before[key][k]}
        if raw_patch:
            patches[key] = {"raw": raw_patch}

    print(f"rows changed: {len(patches):,}")
    confidences: dict[str, int] = {}
    for p in patches.values():
        conf = (p.get("raw", {}).get("recorded_comps") or {}).get("confidence")
        if conf:
            confidences[conf] = confidences.get(conf, 0) + 1
    print(f"  by confidence: {confidences}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_carteret_recorded_comps", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_carteret_recorded_comps": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
