#!/usr/bin/env python3
"""One-time catch-up for enrichment_cama_condition.py against Spartanburg SC.

FOUND round 69 (2026-11-19), continuing round 68's systematic built-but-
unapplied audit, which flagged Spartanburg as one of six cama_condition
counties with <7% of its eligible population tagged (34 of 39,414 eligible
rows) but had NOT live-reverified the source or sized real catch-up yield.

LIVE-REVERIFIED here, and it was NOT simply an unapplied-backfill case like
Buncombe tax_relief (round 68) -- a real field-mapping bug was found and
FIXED first (same module, same file):

  * enrichment_cama_condition.py's Spartanburg entry was wired (2026-08-19)
    against `GISParcelNumber` -- a DIFFERENT per-building geometry id, not the
    board's parcel_id namespace. A 600-row live sample against the UNFIXED
    module matched 0/600.
  * The board's parcel_id ('7-09-01-023.00') turned out to be this layer's
    `MAPNUMBER` field VERBATIM -- confirmed exact-string on 5/5 hand-sampled
    leads, each returning CardNumber=1 with a populated ConditionFactor
    (164,417 of 183,465 total rows are CardNumber=1; all of those carry a
    ConditionFactor). MAPNUMBER's dashes/decimal are load-bearing (a digit-
    stripped '7090102300' is a DIFFERENT, non-existent key), so the module's
    PIN-join helpers gained a new `pin_raw` mode that skips digit-stripping
    for this one source instead of digit-stripping every lead's parcel_id.
  * Re-verified on the SAME 600-row live sample after the fix:
    matched=485 (80.8%), stamped=467 (77.8%, condition+grade+year),
    distressed=3 (0.5% -- genuine new Poor/Unsound flags), filled_year=0
    (Spartanburg leads already carry year_built from elsewhere; this source
    still backfills it when missing on other counties).

Board census (2026-11-19): 39,414 eligible (parcel_id, non-LAND) Spartanburg
SC rows, only 34 already tagged -- by far the largest of the six cama_
condition counties round 68 flagged, now the largest LIVE-CONFIRMED opportunity
this session (NC Carteret's own cama_condition gap, built alongside this one,
is a distant second at 1,653 eligible). Extrapolating the 600-row sample's
77.8% stamp rate across the full 39,380 untagged-eligible population projects
on the order of 30,000+ condition/grade/year stamps and several hundred new
distress flags.

(NC Onslow, NC Gaston, NC Buncombe's OWN cama_condition source -- distinct from
the Buncombe tax_relief ArcGIS layer round 68 fixed -- all re-verified DEAD or
near-dead this round: Onslow 1.0% match [5/501, likely limited to parcels
built 2023-2024 that happen to share numbering with this layer], Gaston 0.0%
match [board parcel_id does not resolve under any PIN/oldPIN/AKPAR variant
tried], Buncombe 0.0% match [direct exact-match also empty; a format-correct
PIN15 key still finds nothing in the live table, plus an intermittent batch-
query failure (wall_skip) -- a different, NOT-yet-diagnosed issue from
Spartanburg's clean field-rename fix]. None of the three got a backfill
script this round -- see the round-69 report for the live numbers.)

Scoped to one county, same shape as backfill_lincoln_tax_relief.py /
backfill_buncombe_tax_relief.py. Unlike those, this module also fills
Listing.year_built (a top-level field, not under raw) when missing, so this
script watches and patches that field too.

    python scripts/backfill_spartanburg_cama_condition.py --dry-run --max-sample 2000
    python scripts/backfill_spartanburg_cama_condition.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_spartanburg_cama_condition.py --allow-large
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
from foreclosure_scraper.enrichment_cama_condition import enrich_cama_condition  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

COUNTY = "Spartanburg"
STATE = "SC"
_RAW_WATCH_KEYS = ("condition_cama", "distressed", "condition_tier", "condition_source")


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

    print(f"streaming board for {COUNTY}, {STATE} rows with a parcel_id, not LAND, "
          f"not already tagged condition_cama...")
    keyed: dict[str, Listing] = {}
    before_raw: dict[str, dict] = {}
    before_year: dict[str, int | None] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != COUNTY or (rec.get("state") or "").strip() != STATE:
            continue
        if not rec.get("parcel_id"):
            continue
        if (rec.get("property_kind") or "").strip().lower() == "land":
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if raw.get("condition_cama"):
            continue  # already tagged, nothing new to gain
        li = Listing.model_validate(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before_raw[key] = {k: copy.deepcopy(li.raw.get(k)) if isinstance(li.raw, dict) else None
                            for k in _RAW_WATCH_KEYS}
        before_year[key] = li.year_built
        if args.max_sample and len(keyed) >= args.max_sample:
            break

    print(f"candidate rows this run: {len(keyed):,}")
    print("running enrich_cama_condition() (batched PIN IN(...) queries, ~100 PINs/query)...")

    async def run():
        return await enrich_cama_condition(list(keyed.values()), concurrency=6)

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        after_raw = {k: li.raw.get(k) if isinstance(li.raw, dict) else None for k in _RAW_WATCH_KEYS}
        raw_patch = {k: after_raw[k] for k in _RAW_WATCH_KEYS if after_raw[k] != before_raw[key][k]}
        patch: dict = {}
        if raw_patch:
            patch["raw"] = raw_patch
        if li.year_built != before_year[key] and li.year_built is not None:
            patch["year_built"] = li.year_built
        if patch:
            patches[key] = patch

    print(f"rows changed: {len(patches):,}")
    condition_counts: dict[str, int] = {}
    distressed_n = 0
    year_filled_n = 0
    for p in patches.values():
        cond = (p.get("raw", {}).get("condition_cama") or {}).get("condition")
        if cond:
            condition_counts[cond] = condition_counts.get(cond, 0) + 1
        if p.get("raw", {}).get("distressed") is True:
            distressed_n += 1
        if "year_built" in p:
            year_filled_n += 1
    print(f"  by condition: {condition_counts}")
    print(f"  distressed (new): {distressed_n:,}")
    print(f"  year_built filled: {year_filled_n:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_spartanburg_cama_condition", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_spartanburg_cama_condition": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
