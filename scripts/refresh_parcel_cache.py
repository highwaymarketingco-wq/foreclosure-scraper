#!/usr/bin/env python3
"""Weekly parcel-cache refresh — bulk-download every configured county's parcel
layer into local SQLite (completeness-verified, overwrite-in-place). Runs just READ
the cache via parcel_cache.lookup(); this job is the only thing that hits the county
GIS in bulk. Schedule weekly (parcels are slow-moving). ~5-10 min for all counties.

    python scripts/refresh_parcel_cache.py               # all configured counties
    python scripts/refresh_parcel_cache.py Buncombe      # one county
    python scripts/refresh_parcel_cache.py Beaufort:SC   # the SC half of a two-state name
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.parcel_cache import (  # noqa: E402
    PARCEL_LAYERS, SC_DUAL_LAYERS, refresh_county)


def targets(argv: list[str]) -> list[tuple[str, str | None]]:
    """(county, state) pairs. "Name:SC" names the SC half of a DUAL_STATE_COUNTIES county
    (parcel_cache.SC_DUAL_LAYERS); a bare name keeps its old meaning."""
    if not argv:
        return [(c, None) for c in PARCEL_LAYERS] + [(c, "SC") for c in SC_DUAL_LAYERS]
    out = []
    for a in argv:
        name, _, st = a.partition(":")
        out.append((name, st.strip().upper() or None))
    return out


async def main() -> int:
    ok = bad = 0
    for county, state in targets(sys.argv[1:]):
        r = await refresh_county(county, state)
        label = f"{county}:{state}" if state else county
        if r.get("ok"):
            ok += 1
            print(f"  [OK]   {label:14} {r['downloaded']:>7,}/{r['expected']:,} parcels "
                  f"{r['seconds']:>5}s {r['mb']:>5} MB")
        else:
            bad += 1
            print(f"  [FAIL] {label:14} {r.get('error','?')}  "
                  f"(downloaded {r.get('downloaded')}/{r.get('expected')})")
    print(f"\n{ok} refreshed, {bad} failed. Cache: data/parcel_cache/")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
