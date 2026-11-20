#!/usr/bin/env python3
"""One-time catch-up for enrichment_cama_condition.py against Gaston NC.

FOUND round 69 (2026-11-19): a 600-row live sample against the (then-)
current module matched 0/600. Round 69 tried PIN (10-digit, 15-digit
zero-padded), oldPIN, AKPAR -- none resolved against the live layer, and
flagged the root cause as unfound, needing a fresh investigation of the
layer's actual field list via a live /query?f=json metadata call rather than
guessed field names.

ROOT CAUSE FOUND + FIXED round 70 (2026-11-19). The live metadata call named
in round 69's own instruction: Gaston's `PIN` field IS the right field --
but it is stored DASHED ('3546-54-0134', confirmed live), and
enrichment_cama_condition.py's generic `_pin_key()` digit-strips every
parcel_id by default (the county's config carried `pin_pad15=True`, which
only changes PADDING *after* that strip -- it never stops it). The board's
OWN Gaston parcel_id is ALSO commonly dashed ('3584-60-1097') -- so the
digit-stripped lookup key ('3584601097') never matched what the layer
actually stores, on every single lead, regardless of PIN/oldPIN/AKPAR. This
is the exact same bug class round 69 found and fixed for SC:Spartanburg's
MAPNUMBER (dashes load-bearing, not punctuation). Fix: `pin_raw=True`
(use the parcel_id exactly as stored, no digit-stripping), same as
Spartanburg's own entry.

Live-verified round 70, through the UNCHANGED-except-for-this-one-flag
module: a 600-row real Gaston NC sample (parcel_id present, non-LAND) is
56.3% dashed-format parcel_id / 43.7% digits-only (a real, measured split --
Gaston's board rows do not all share one shape, unlike Carteret/Spartanburg).
`pin_raw` only ever matches the dashed subset (digit-only parcel_ids have no
dashes to preserve, so they query the same way either way and still miss --
Gaston's `PIN` field never stores a bare-digit value). Result: matched
335/600 (55.8% -- almost exactly the dashed-format share, confirming the
mechanism), stamped (a valid YEARBLT found) 148/600 (24.8% of ALL eligible,
44.2% of matches). Gaston's CAMA_SOURCES entry has condition_field=grade_
field=None by design (YEARBLT + SQFT only, no bulk Condition/Grade in this
county's layer) -- so every stamp here is year_built provenance, not a
distress signal; `filled_year` was 0 in this particular 600-row sample
(those rows already carried year_built from another source), but a full
board run can still backfill year_built wherever something else left it
missing, and the raw['condition_cama'] stamp itself (source + year) is
real, new, previously-impossible-to-attach data.

NOT fixed by this change (documented, not re-chased): the ~44% of Gaston
leads whose parcel_id has no dashes cannot resolve against this one PIN
field/join-mode (a second, digits-only join via `oldPIN` would need its own
code path -- the module supports one pin_field per county entry today, not
a fallback chain -- out of scope for this round's one-line fix).

Scoped to one county, same shape as backfill_carteret_cama_condition.py /
backfill_spartanburg_cama_condition.py (round 69's two cama_condition
catch-ups) / backfill_lincoln_tax_relief.py. Unlike Carteret's script, this
module's year_built backfill is the ONLY watched signal for Gaston (no
condition/grade/distressed ever fires here), but the raw watch keys are kept
the same shape as the Carteret script for consistency and because a future
layer-schema change could still populate them.

    python scripts/backfill_gaston_cama_condition.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_gaston_cama_condition.py --allow-large
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

COUNTY = "Gaston"
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
    dashed = sum(1 for li in keyed.values() if "-" in (li.parcel_id or ""))
    print(f"  dashed-format parcel_id (the only subset this fix can match): "
          f"{dashed:,} ({100*dashed/len(keyed):.1f}%)" if keyed else "")
    print("running enrich_cama_condition() (batched PIN IN(...) queries, ~100 PINs/query, "
          "pin_raw -- dashed parcel_id used as-is)...")

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
    distressed_n = 0
    year_filled_n = 0
    for p in patches.values():
        if p.get("raw", {}).get("distressed") is True:
            distressed_n += 1
        if "year_built" in p:
            year_filled_n += 1
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

    with board_lock(REPO, owner="backfill_gaston_cama_condition", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_gaston_cama_condition": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
