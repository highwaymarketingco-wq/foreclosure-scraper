#!/usr/bin/env python3
"""One-time catch-up for enrichment_tax_relief.py against Buncombe NC.

FOUND round 68 (2026-11-19), via a systematic audit for more Lincoln-shaped
("built but never backfilled") gaps after round 67's Lincoln NC win. Buncombe's
('NC', 'Buncombe') entry is the FIRST and (unlike every other entry in
_RELIEF_LAYERS) UNDATED county in enrichment_tax_relief.py -- no "20XX-XX-XX
addition" note, suggesting it has been wired since this module's creation --
yet the live board carried ZERO rows with raw['tax_relief'] for Buncombe
before this script ran. This is the SAME shape as Lincoln's gap, just older
and bigger: being the oldest entry did not protect it from the same miss,
because nothing ever ran a catch-up pass against EXISTING rows (only rows
that pass through live re-enrichment pick up a wired signal; see
feedback_built_but_unwired_pattern_2026-10-28.md).

Buncombe's entry flags the NC elderly/disabled/blind homestead exemption
(Exempt IN ('ELD','DIS','BLD')) -- a senior OWNER-OCCUPANT signal, scored by
distress_score.py as a LIFE_EVENT ("senior_exemption", weight 8) for kind in
(elderly/disabled/blind/homestead_exemption). Unlike Henderson/Gaston/
Rutherford's present-use ag rollback deferral (a farm/forest programme that
barely intersects this board's residential population, per that module's own
"MEASURED YIELD" note), a homestead exemption is common among long-tenured
residential owner-occupants -- exactly this board's population.

SYSTEMATIC AUDIT, round 68: every (state, county) tax_relief gap was
re-verified live (returnCountOnly against the exact where_extra
enrich_tax_relief() uses) and sized by a direct exact + alnum-stripped PIN
intersection against the board's own parcel_id population (the same cheap
method Lincoln's round-67 fix used for sizing, before the slow per-row
enrich_tax_relief() apply):

    county      live_flagged  board_eligible  intersection_estimate
    Buncombe           3,625           9,068                  2,786
    Henderson          1,576           2,793                     19
    Gaston             1,574          24,270                     35
    Rutherford         2,188          10,234                      5
    Burke                  0             697                      0  (DEAD:
        live USE_VALUE_DEFERRED/TOTAL_DEFERRED_VALUE population is 0 countywide
        right now, despite the module docstring's 2026-10-02 claim of 1,560 --
        re-verified field types (esriFieldTypeDouble, correct), re-tried three
        where-clause variants, all returned 0. The county's deferral roll
        appears to have been reassessed to zero since; not a query bug, not a
        viable backfill target today.)

Buncombe is by far the largest real opportunity found this round -- larger
than Lincoln's own 1,800-row win. Henderson/Gaston/Rutherford's estimates (19/
35/5) confirm the module's own "MEASURED YIELD" note that ag-deferral barely
intersects this board; not worth their own backfill scripts at this size.

Scoped to one county, same shape as backfill_lincoln_tax_relief.py /
backfill_lexington_tax_relief.py.

    python scripts/backfill_buncombe_tax_relief.py --dry-run --max-queries 500
    python scripts/backfill_buncombe_tax_relief.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_buncombe_tax_relief.py --allow-large
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
from foreclosure_scraper.enrichment_tax_relief import enrich_tax_relief  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

COUNTY = "Buncombe"
STATE = "NC"
_RAW_WATCH_KEYS = ("tax_relief", "rollback_exposure")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-queries", type=int, default=20000)
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print(f"streaming board for {COUNTY}, {STATE} rows with a parcel_id...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != COUNTY or (rec.get("state") or "").strip() != STATE:
            continue
        if not rec.get("parcel_id"):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if raw.get("tax_relief"):
            continue  # already tagged, nothing new to gain
        li = Listing.model_validate(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = {k: copy.deepcopy(li.raw.get(k)) if isinstance(li.raw, dict) else None
                       for k in _RAW_WATCH_KEYS}

    print(f"candidate rows this run: {len(keyed):,}")
    print("running enrich_tax_relief() (sequential per-row ArcGIS queries, ~0.1-0.4s each)...")

    async def run():
        return await enrich_tax_relief(list(keyed.values()), max_queries=args.max_queries)

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        after = {k: li.raw.get(k) if isinstance(li.raw, dict) else None for k in _RAW_WATCH_KEYS}
        if after == before[key]:
            continue
        raw_patch = {k: after[k] for k in _RAW_WATCH_KEYS if after[k] != before[key][k]}
        if raw_patch:
            patches[key] = {"raw": raw_patch}

    print(f"rows changed: {len(patches):,}")
    kind_counts: dict[str, int] = {}
    for p in patches.values():
        kind = (p.get("raw", {}).get("tax_relief") or {}).get("kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
    print(f"  by kind: {kind_counts}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_buncombe_tax_relief", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_buncombe_tax_relief": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
