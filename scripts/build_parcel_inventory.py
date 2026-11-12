#!/usr/bin/env python
"""Build the full per-county PARCEL INVENTORY into data/parcel_inventory.db.

  python scripts/build_parcel_inventory.py                 # all 18 counties
  python scripts/build_parcel_inventory.py NC:Polk SC:Anderson   # a subset

Pulls every parcel (id / owner / situs / mailing / value) per county via ArcGIS
pagination, through the shared rate-limited client (polite per-host). Intended
to run monthly (launchd/cron). Enrichment then resolves any property from the
local cache first and only hits the network for genuinely new parcels.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.parcel_inventory import build_inventory  # noqa: E402


def _parse(args: list[str]):
    only = [tuple(a.split(":", 1)) for a in args if ":" in a]
    return only or None


async def _main() -> int:
    only = _parse(sys.argv[1:])
    t0 = time.time()
    counts = await build_inventory(only)
    print(f"\nPARCEL INVENTORY ({time.time() - t0:.0f}s):")
    for k, v in sorted(counts.items()):
        print(f"  {k:20} {v:>9,}")
    print(f"  {'TOTAL':20} {sum(counts.values()):>9,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
