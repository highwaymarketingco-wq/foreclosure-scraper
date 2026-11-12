#!/usr/bin/env python3
"""One-time backfill: run the existing, already-wired enrich_with_rollback_exposure() --
already covers Mecklenburg NC via a bulk ArcGIS CAMA fetch (enrichment_rollback_deferral.py)
-- against the full historical board, not just whatever rows happened to be in main.py's own
`enriched` working set on some past run. No dedicated backfill script existed for this county
yet (gap_matrix: 0.0% done, 18,552 rows, "code covers this county... but nothing landed here").

The bulk GIS fetch happens ONCE per call regardless of how many leads are passed in -- unlike
Gaston's/Johnston's per-row live-fetch pattern tonight, this needs no batching: pass the whole
candidate set in one call. Only the live top-up for CONFIRMED matches is capped
(ROLLBACK_MECKLENBURG_LIVE_CAP, default 50) -- most matches land with the bulk GIS record alone,
a smaller subset additionally gets live_confirmed=True.

Only stamps raw['rollback_exposure'] on an actual match (same convention this module's
Buncombe/Anderson/Wake lanes already use) -- a non-match gets nothing written, same as every
other county on this producer. REQUIRES parcel_id (same gate _lead_keys() itself uses) --
matches feedback_dedupe_key_url_fallback_landmine_2026-10-22.md's guard: never let a patch
candidate's identity rest on source_url alone.

    python scripts/backfill_mecklenburg_rollback_exposure.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_mecklenburg_rollback_exposure.py
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
from foreclosure_scraper.enrichment_rollback_deferral import (  # noqa: E402
    enrich_with_rollback_exposure,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)


def _candidates(docs_dir: Path) -> list[tuple[str, Listing]]:
    out = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county != "Mecklenburg":
            continue
        if not rec.get("parcel_id"):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if isinstance(raw.get("rollback_exposure"), dict):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = dict(raw)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        out.append((key, li))
    return out


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

    cands = _candidates(docs_dir)
    print(f"Mecklenburg NC eligible candidates (parcel_id present, no rollback_exposure yet): "
          f"{len(cands):,}")
    if not cands:
        print("nothing to do.")
        return 0

    listings = [li for _, li in cands]
    stats = asyncio.run(enrich_with_rollback_exposure(listings))
    print(f"stats: {stats}")

    patches = {}
    for key, li in cands:
        if isinstance(li.raw, dict) and isinstance(li.raw.get("rollback_exposure"), dict):
            patches[key] = {"raw": {"rollback_exposure": li.raw["rollback_exposure"]}}

    print(f"patches staged (positive match found): {len(patches):,}")

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        return 0
    if not patches:
        print("nothing to patch (0 positive matches).")
        return 0

    with board_lock(REPO, owner="mecklenburg_rollback_backfill", wait=600, poll=10):
        pstats = patch_existing_rows(
            patches, {"mecklenburg_rollback_backfill": stats}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
