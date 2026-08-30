#!/usr/bin/env python3
"""Weekly parcel-cache refresh — bulk-download every configured county's parcel
layer into local SQLite (completeness-verified, overwrite-in-place). Runs just READ
the cache via parcel_cache.lookup(); this job is the only thing that hits the county
GIS in bulk. Schedule weekly (parcels are slow-moving). ~5-10 min for all counties.

    python scripts/refresh_parcel_cache.py            # all configured counties
    python scripts/refresh_parcel_cache.py Buncombe   # one county
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.parcel_cache import PARCEL_LAYERS, refresh_county  # noqa: E402


async def main() -> int:
    want = sys.argv[1:] or list(PARCEL_LAYERS)
    ok = bad = 0
    for county in want:
        r = await refresh_county(county)
        if r.get("ok"):
            ok += 1
            print(f"  [OK]   {county:14} {r['downloaded']:>7,}/{r['expected']:,} parcels "
                  f"{r['seconds']:>5}s {r['mb']:>5} MB")
        else:
            bad += 1
            print(f"  [FAIL] {county:14} {r.get('error','?')}  "
                  f"(downloaded {r.get('downloaded')}/{r.get('expected')})")
    print(f"\n{ok} refreshed, {bad} failed. Cache: data/parcel_cache/")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
