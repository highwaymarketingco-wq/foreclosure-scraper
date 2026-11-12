#!/usr/bin/env python3
"""One-time catch-up for enrichment_tax_relief.py against Lexington SC.

FOUND 2026-10-30: wired a new ('SC', 'Lexington') entry into
enrichment_tax_relief.py's _RELIEF_LAYERS (Homestead/AG fields, same SC
homestead-exemption statute York SC's HOMESTEAD already covers). The
enrichment only fires going forward for newly-scraped/re-enriched rows, so
the board's existing 1,707 Lexington SC rows that already carry a
parcel_id need a one-time catch-up pass, same shape as the Mecklenburg
gis_attrs backfill. Scoped to one county -- enrich_tax_relief() is cheap
(one query per candidate row) and this population is small and measured.

    python scripts/backfill_lexington_tax_relief.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_lexington_tax_relief.py --allow-large
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

COUNTY = "Lexington"
STATE = "SC"
_RAW_WATCH_KEYS = ("tax_relief", "rollback_exposure")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
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
        return await enrich_tax_relief(list(keyed.values()), max_queries=len(keyed) or 1)

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
    homestead_hits = sum(1 for p in patches.values()
                         if (p.get("raw", {}).get("tax_relief") or {}).get("kind")
                         == "homestead_exemption")
    ag_hits = sum(1 for p in patches.values()
                 if (p.get("raw", {}).get("tax_relief") or {}).get("kind")
                 == "use_value_deferral")
    print(f"  homestead_exemption: {homestead_hits:,}  use_value_deferral (ag): {ag_hits:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_lexington_tax_relief", wait=3600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_lexington_tax_relief": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
