#!/usr/bin/env python3
"""One-time catch-up for enrichment_owner_mailing.py against Carteret NC,
scoped to this one county only (NOT the whole-board patch_owner_mailing.py
sweep, which has no county filter and is out of scope for this change).

FOUND + FIXED round 70 (2026-11-19), alongside backfill_carteret_recorded_
comps.py (the primary ask this round -- see that script's docstring for the
full COUNTY_GIS fix). Before this round, Carteret NC had NO dedicated
"NC:Carteret" entry in enrichment_owner_mailing.COUNTY_GIS at all, so every
Carteret owner_mailing resolution fell through to the NC OneMap statewide
fallback (`is_reachable()`: "NC OneMap covers all 100 NC counties"). Board
census (2026-11-19, this session): of 2,453 Carteret NC rows, 1,839 had no
owner_mailing yet despite that fallback; 1,344 of those 1,839 carry a
parcel_id. Live-verified round 70: a 600-PIN15 batch against the NEW
dedicated spec (same parcel MapServer recorded_comps now also reads) matched
594/600 (99.0%), with OWNER populated on 100% of matches and a mailing
address (MAIL_ADDRESS1) on 99.7% -- a real, materially better resolution
path than whatever was leaving these 1,344+ rows unresolved via OneMap.

This is additive, not a replacement: `_resolve_one()` tries the dedicated
COUNTY_GIS spec FIRST, then NC OneMap only if that spec didn't resolve, or to
supplement a missing value -- so this backfill can only fill gaps, never
regress an already-resolved row (rows with owner_mailing already set are
excluded below, same gate `is_target()`/`has_mailing()` already enforce).

Scoped to one county, same shape as backfill_carteret_cama_condition.py /
backfill_carteret_recorded_comps.py, adapted for enrichment_owner_mailing.
enrich_owner_mailing() (mutates listings in place, returns a stats dict, and
fills several top-level fields -- parcel_id, bedrooms/bathrooms via BEDROOMS/
BATHROOMS which DO match this module's generic _extract_specs patterns, and
tax_value/market_value/assessed_value via the NC-OneMap value-supplement
path -- not just raw['owner_mailing']).

    python scripts/backfill_carteret_owner_mailing.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_carteret_owner_mailing.py --allow-large
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
from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing, is_target  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

COUNTY = "Carteret"
STATE = "NC"
_RAW_WATCH_KEYS = ("owner_mailing", "cama", "distressed")
_SCALAR_WATCH_FIELDS = ("parcel_id", "bedrooms", "bathrooms",
                        "tax_value", "market_value", "assessed_value")


def _snapshot(li: Listing) -> dict:
    out = {k: (copy.deepcopy(li.raw.get(k)) if isinstance(li.raw, dict) else None)
           for k in _RAW_WATCH_KEYS}
    for f in _SCALAR_WATCH_FIELDS:
        out[f] = getattr(li, f)
    return out


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

    print(f"streaming board for {COUNTY}, {STATE} owner_mailing targets "
          f"(is_target(): reachable, has an address/parcel_id, not already mailable)...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != COUNTY or (rec.get("state") or "").strip() != STATE:
            continue
        li = Listing.model_validate(rec)
        if not is_target(li):
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = _snapshot(li)
        if args.max_sample and len(keyed) >= args.max_sample:
            break

    print(f"candidate rows this run: {len(keyed):,}")
    print("running enrich_owner_mailing() (dedicated county PIN15 spec, "
          "NC OneMap fallback/value-supplement, 12-way concurrency)...")

    async def run():
        return await enrich_owner_mailing(list(keyed.values()), max_concurrency=12)

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        snap = _snapshot(li)
        raw_patch = {k: snap[k] for k in _RAW_WATCH_KEYS if snap[k] != before[key][k]}
        patch: dict = {}
        if raw_patch:
            patch["raw"] = raw_patch
        for f in _SCALAR_WATCH_FIELDS:
            if snap[f] != before[key][f] and snap[f] is not None:
                patch[f] = snap[f]
        if patch:
            patches[key] = patch

    print(f"rows changed: {len(patches):,}")
    sources: dict[str, int] = {}
    absentee_n = out_of_state_n = 0
    for p in patches.values():
        om = (p.get("raw", {}) or {}).get("owner_mailing")
        if isinstance(om, dict):
            src = om.get("source")
            if src:
                sources[src] = sources.get(src, 0) + 1
            if om.get("absentee"):
                absentee_n += 1
            if om.get("out_of_state"):
                out_of_state_n += 1
    print(f"  by source: {sources}")
    print(f"  absentee (new): {absentee_n:,}  out_of_state (new): {out_of_state_n:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_carteret_owner_mailing", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_carteret_owner_mailing": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
