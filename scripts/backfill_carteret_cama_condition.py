#!/usr/bin/env python3
"""One-time catch-up for enrichment_cama_condition.py against Carteret NC.

FOUND round 69 (2026-11-19), continuing round 68's systematic built-but-
unapplied audit, which flagged Carteret as one of six cama_condition counties
with <7% of its eligible population tagged (59 of 1,653 eligible rows) but
had NOT live-reverified the source or sized real catch-up yield.

LIVE-REVERIFIED (unlike Spartanburg's sibling gap, this one needed NO code
fix -- the existing PIN15 join, as wired, just works): a 600-row live sample
against the UNCHANGED module matched 572/600 (95.3%), stamped 351/600
(58.5%, condition+grade+year), distressed 24/600 (4.0% -- genuine Poor/
VeryPoor/Unsound flags), filled_year 346/600 (missing year_built backfilled).

Board census (2026-11-19): 1,653 eligible (parcel_id, non-LAND) Carteret NC
rows, only 59 already tagged. Extrapolating the 600-row sample's 58.5% stamp
rate across the 1,594 untagged-eligible population projects on the order of
930 condition/grade/year stamps and roughly 65 new distress flags -- a real,
clean win, smaller than Spartanburg's own gap (39,414 eligible, built
alongside this one in backfill_spartanburg_cama_condition.py) but the
strongest per-row DISTRESS signal of the two (Carteret's layer carries a
real Condition field; Spartanburg's ConditionFactor skews heavily average/
good/fair in the sample, distressed only 0.5%, vs Carteret's 4.0%).

Scoped to one county, same shape as backfill_lincoln_tax_relief.py /
backfill_buncombe_tax_relief.py. Unlike those, this module also fills
Listing.year_built (a top-level field, not under raw) when missing, so this
script watches and patches that field too.

    python scripts/backfill_carteret_cama_condition.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_carteret_cama_condition.py --allow-large
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

COUNTY = "Carteret"
STATE = "NC"
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

    with board_lock(REPO, owner="backfill_carteret_cama_condition", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_carteret_cama_condition": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
