#!/usr/bin/env python3
"""One-time catch-up for enrichment_recorded_comps.py against Pickens SC.

FOUND round 69 (2026-11-19). Round 68's audit covered cama_condition; this
session also live-verified the five recorded_comps gap-candidates round 68
flagged as "0 tagged everywhere, not yet live-verified" (NC Carteret, SC
Anderson, SC Laurens, SC Pickens, SC Spartanburg). recorded_comps is a
VALUATION signal (median $/sqft from real nearby recorded sales -> ARV), not
a distress signal -- round 68 called it lower priority. Live verification
confirms that framing for four of the five, but for a STRUCTURAL reason
round 68 did not have: enrich()'s own eligibility filter
(`RECORDED_COMP_CONFIG[...].get("sqft")`) drops any county whose config has
no heated-sqft field, and three of the five (Anderson, Laurens, Spartanburg)
are configured `sqft=None` by design ("SC layers carry price+date+geometry
but NO heated-sqft on the owner layer... ready the moment a CAMA sqft join
lands" -- per the module's own docstring) -- these are NOT catch-up
candidates at all under the current code; they need new engineering (a CAMA
sqft join), not a backfill script. NC Carteret is also structurally dead
today for a different reason: `enrichment_owner_mailing.COUNTY_GIS` has NO
"NC:Carteret" entry, so `enrich()`'s `base = COUNTY_GIS.get(...)` is None and
every Carteret lead is skipped before any network call -- also not a
same-shape catch-up target (needs a COUNTY_GIS entry added first).

Pickens is the ONE exception: `sqft="CalcArea"` IS configured, and
`COUNTY_GIS["SC:Pickens"]` DOES carry a url -- so it is reachable today, and
not just reachable: a 150-row live sample against the UNCHANGED module
tagged 150/150 (100%), each with >=3 qualifying nearby recorded sales
(example: 29 comps, $28.84/sqft median). No code change needed.

Board census (2026-11-19): 5,452 Pickens SC rows with both latitude and
longitude (this module's only eligibility gate -- parcel_id is not required),
zero already tagged recorded_comps. A 100% sample match rate is an upper
bound (clustering in a 150-row file-order sample can inflate it slightly
versus the true county-wide rate), but even a materially lower true rate
still implies several thousand new valuation-signal stamps -- the largest
real, LIVE, zero-code-change recorded_comps opportunity found this round.

Scoped to one county, same shape as backfill_lincoln_tax_relief.py /
backfill_buncombe_tax_relief.py, adapted for enrichment_recorded_comps.enrich()
(which mutates listings in place and returns them, rather than returning a
stats dict).

    python scripts/backfill_pickens_recorded_comps.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_pickens_recorded_comps.py --allow-large
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

COUNTY = "Pickens"
STATE = "SC"
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

    with board_lock(REPO, owner="backfill_pickens_recorded_comps", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_pickens_recorded_comps": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
