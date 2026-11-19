#!/usr/bin/env python3
"""One-time catch-up for enrichment_tax_relief.py against Lincoln NC.

FOUND round 67 (2026-11-19): Lincoln NC's ('NC', 'Lincoln') entry has been
wired into enrichment_tax_relief.py's _RELIEF_LAYERS since 2026-10-02
(LANDEFERRED flag off arcgisserver.lincolncountync.gov's county parcel
layer, insecure_tls=True for the host's broken TLS chain). The enrichment
only fires going forward for newly-scraped/re-enriched rows -- same gap
backfill_lexington_tax_relief.py (2026-10-30) fixed for Lexington SC -- and
in the five-plus weeks since Lincoln was wired, nothing ever ran a catch-up
pass against the board's EXISTING rows. Live-reverified round 67:
  - Streamed the real board: 18,841 Lincoln NC rows, 17,090 with a
    parcel_id, ZERO already carrying raw['tax_relief'] or
    raw['rollback_exposure'] -- the full existing population is untouched.
  - Re-queried the live layer: still 2,444 PINs with LANDEFERRED<>0 (exact
    match to the module docstring's 2026-10-02 count), same field names,
    same TLS workaround needed (verify=True throws "unable to get local
    issuer certificate").
  - Direct set-intersection of the live layer's 2,444 flagged PINs against
    the board's 17,090 Lincoln parcel_ids (exact + alnum-stripped match,
    same as _pid_variants' two cheapest forms): 1,800 real hits. This is
    the single largest rollback_exposure catch-up found this project --
    nearly double every per-county rollback_exposure win landed in rounds
    63-66 (Pender 11, Durham, Yancey, Hertford) combined.

Scoped to one county -- enrich_tax_relief() is cheap (one query per
candidate row, capped by max_queries) and this population is measured.
Same shape as backfill_lexington_tax_relief.py / the Mecklenburg gis_attrs
backfill.

    python scripts/backfill_lincoln_tax_relief.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_lincoln_tax_relief.py --allow-large
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

COUNTY = "Lincoln"
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
    print("running enrich_tax_relief()...")

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
    deferral_hits = sum(1 for p in patches.values()
                        if (p.get("raw", {}).get("tax_relief") or {}).get("kind")
                        == "use_value_deferral")
    print(f"  use_value_deferral (LANDEFERRED flag): {deferral_hits:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_lincoln_tax_relief", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_lincoln_tax_relief": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
