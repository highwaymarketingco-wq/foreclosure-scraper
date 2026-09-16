#!/usr/bin/env python3
"""Apply cached raw['gis_attrs_full'] bags onto their Listing's top-level
fields, for rows where that never happened.

Found 2026-09-16: enrichment_parcel_from_geo._parcel_from_point_nc() stashes
the full matched NC OneMap attribute bag into raw['gis_attrs_full'] (siteadd,
ownname, parval, etc.) for provenance/reuse -- but the point-in-polygon path
only ever calls _clean_parcel()/writes li.parcel_id with it; it never calls
enrichment_arcgis._apply_attrs(), the function that actually maps those raw
field names onto li.tax_value / zoning / acreage / year_built / bedrooms /
bathrooms / living_sqft / raw['gis']['owner'] etc. Same story for any other
enricher that stashed a gis_attrs_full bag without a follow-up apply pass.

Board-wide: 12,308 rows carry raw.gis_attrs_full.parval (a real assessed
value), but only 1,677 of those already have a top-level value field set --
10,631 rows have real, already-fetched value/attribute data sitting unused.

_apply_attrs() is pure, synchronous, and additive-only (its `maybe()` helper
never overwrites a field that already has a value, and _match_confident /
_centroid are absent from these cached bags so it correctly skips writing
parcel_id or moving coordinates -- both already set by the resolver that
created the bag). No network calls; this is a pure in-memory pass.

    python scripts/backfill_gis_attrs_full.py --dry-run
    python scripts/backfill_gis_attrs_full.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_arcgis import _apply_attrs  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_gis_attrs_full")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        targets = [
            li for li in rows
            if isinstance(li.raw, dict) and isinstance(li.raw.get("gis_attrs_full"), dict) and li.raw["gis_attrs_full"]
        ]
        print(f"rows with a cached gis_attrs_full bag: {len(targets):,}")

        total_filled = 0
        rows_touched = 0
        field_counts: dict[str, int] = {}
        for li in targets:
            before = {
                "tax_value": li.tax_value, "zoning": li.zoning, "acreage": li.acreage,
                "year_built": li.year_built, "bedrooms": li.bedrooms, "bathrooms": li.bathrooms,
                "living_sqft": li.living_sqft,
            }
            n = _apply_attrs(li, li.raw["gis_attrs_full"])
            if n:
                total_filled += n
                rows_touched += 1
                for k, v in before.items():
                    new = getattr(li, k, None)
                    if v in (None, "", 0) and new not in (None, "", 0):
                        field_counts[k] = field_counts.get(k, 0) + 1

        print(f"\nrows with >=1 new field filled: {rows_touched:,}")
        print(f"total field-fills: {total_filled:,}")
        for k, c in sorted(field_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {k}: {c:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(rows, {"backfill_gis_attrs_full": total_filled}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
