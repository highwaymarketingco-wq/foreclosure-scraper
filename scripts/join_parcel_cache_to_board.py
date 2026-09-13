#!/usr/bin/env python3
"""Join the local parcel cache onto the board. Fills situs, owner mailing, value, sqft.

WHY THIS EXISTS AS A SCRIPT
    100 county caches were built holding 11.5M parcels, 10.8M of them carrying an owner
    MAILING address -- and the board's mailing coverage stayed at 65%, because
    enrich_gis_attrs only runs inside a full pipeline run and no run had landed since.
    The single biggest contact win available was sitting on disk, unused. SC owner
    contact is the measured binding constraint (Cherokee SC was at 1% mailing).

SAFETY
  * FILLS ONLY. Never overwrites a value the board already has, never adds or removes a
    row, and asserts the row count is unchanged.
  * The cache is keyed by county NAME with no state, so a lookup is only attempted when
    the county is not one of the four names that exist in BOTH Carolinas -- Beaufort,
    Cherokee, Lee, Union. Reading NC parcel data onto an SC lead would be worse than
    leaving the row empty.

    python scripts/join_parcel_cache_to_board.py --dry-run
    python scripts/join_parcel_cache_to_board.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

#: County names that exist in BOTH NC and SC. The cache key carries no state, so these
#: are skipped rather than risk serving one state's parcels to the other's leads.
AMBIGUOUS = {"beaufort", "cherokee", "lee", "union"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.parcel_cache import lookup
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="cache_join")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        c = Counter()
        for li in rows:
            if not li.parcel_id:
                c["no parcel_id"] += 1
                continue
            county = (li.county or "").replace(" County", "").strip()
            if not county:
                c["no county"] += 1
                continue
            if county.lower() in AMBIGUOUS:
                c["skipped: name exists in both states"] += 1
                continue
            try:
                hit = lookup(county, li.parcel_id)
            except Exception:  # noqa: BLE001
                c["lookup error"] += 1
                continue
            if not hit:
                c["cache miss"] += 1
                continue
            c["cache HIT"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}

            if hit.get("owner_mailing"):
                g = li.raw.setdefault("gis", {})
                if not g.get("mailing"):
                    g["mailing"] = hit["owner_mailing"]
                    c["filled owner mailing"] += 1
            if hit.get("address") and not (li.street_address or "").strip():
                li.street_address = hit["address"]
                c["filled situs address"] += 1
            if hit.get("owner") and not (li.owner_name or "").strip():
                li.owner_name = hit["owner"]
                c["filled owner name"] += 1
            if hit.get("market_value") and not li.market_value:
                li.market_value = hit["market_value"]
                c["filled market value"] += 1
            if hit.get("tax_value") and not li.tax_value:
                li.tax_value = hit["tax_value"]
                c["filled tax value"] += 1
            if hit.get("living_sqft") and not li.living_sqft:
                li.living_sqft = hit["living_sqft"]
                c["filled sqft"] += 1
            if hit.get("acreage") and not li.acreage:
                li.acreage = hit["acreage"]
                c["filled acreage"] += 1
            if hit.get("sale_price"):
                g = li.raw.setdefault("gis", {})
                ls = g.setdefault("last_sale", {})
                if not ls.get("amount"):
                    ls["amount"] = hit["sale_price"]
                    c["filled last sale"] += 1

        print()
        for k, n in c.most_common():
            print(f"  {n:>8,}  {k}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert len(rows) == before, "a join must never change the row count"
        write_artifact(rows, {
            "total": before,
            "notes": (f"parcel-cache join: {c['cache HIT']:,} hits, "
                      f"{c['filled owner mailing']:,} owner mailing, "
                      f"{c['filled situs address']:,} situs, {c['filled sqft']:,} sqft"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
