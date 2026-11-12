#!/usr/bin/env python3
"""Run enrichment_marriage_license.enrich_marriage_licenses() over the board rows the
Aumentum ROD adapter actually covers (NC Buncombe + Mecklenburg per commit c4bf4902),
via the same memory-safe streaming-collect + patch_existing_rows() pattern
scripts/resolver_backfill_parcel.py established for this board's real size (~2.6 GB,
over load_board()'s ceiling).

enrich_marriage_licenses() is ALREADY internally scoped to aumentum.AUMENTUM_COUNTIES
and already rate-limits itself (MARRIAGE_LICENSE_MAX_REQUESTS, default 50) and is
already idempotent (skips any row with an existing raw['marriage_license'], match OR
confirmed no-match) -- this script's own pre-filter (state=="NC", county in
{Buncombe, Mecklenburg}) just avoids materializing the other ~200K board rows into
Listing objects before handing the small real candidate set to that function.

    python scripts/backfill_marriage_license.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_marriage_license.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_marriage_license import enrich_marriage_licenses  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.rod import aumentum  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

TARGET_COUNTIES = {c for (s, c) in aumentum.AUMENTUM_COUNTIES if s == "NC"}


def _collect_targets(docs: Path) -> list[Listing]:
    targets: list[Listing] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("state") != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county not in TARGET_COUNTIES:
            continue
        raw = rec.get("raw") or {}
        if isinstance(raw, dict) and raw.get("marriage_license"):
            continue  # already checked (match or confirmed no-match) -- skip before validating
        owner = rec.get("owner_name") or rec.get("defendant")
        if not owner:
            continue
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001
            continue
        targets.append(li)
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    print(f"Aumentum-covered NC counties this run targets: {sorted(TARGET_COUNTIES)}")
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_marriage_license")
    with lock:
        targets = _collect_targets(docs)
        print(f"candidate rows (NC Buncombe/Mecklenburg, owner present, not yet checked): {len(targets):,}")

        pre_keys = {li.dedupe_key(): li for li in targets}

        stats = asyncio.run(enrich_marriage_licenses(targets))
        print(f"\nstats: {stats}")

        pending_patches: dict[str, dict] = {}
        for key, li in pre_keys.items():
            tag = li.raw.get("marriage_license") if isinstance(li.raw, dict) else None
            if tag is None:
                continue
            pending_patches[key] = {"raw": {"marriage_license": tag}}

        print(f"rows to patch: {len(pending_patches):,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        if not pending_patches:
            print("\nnothing to patch (0 stamped this run)")
            return 0

        pstats = patch_existing_rows(
            pending_patches, {"backfill_marriage_license": stats}, docs_dir=docs)
        print(f"\npatch result: {pstats}")
        print(f"patched {pstats['applied']}/{len(pending_patches)} rows "
              f"(existing board: {pstats['existing']:,})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
