"""Smoke-test individual scrapers with a hard timeout.

Run before Run #15 to catch any scraper that's broken right now (anti-bot
escalation, schema change, dead URL) without burning the full pipeline.
Outputs a single line per scraper: SLUG | COUNT | TIME_S | STATUS

Usage:
  uv run python scripts/smoke_one_scraper.py <slug>
  uv run python scripts/smoke_one_scraper.py --all-free
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback

from foreclosure_scraper.scrapers._registry import all_scrapers


# Scrapers that work without API credentials (free public endpoints).
# Excludes: CourtListener (needs token), foreclosure.com (needs login),
# Apify-backed scrapers (needs APIFY_TOKEN), Vision/RentCast.
FREE_SCRAPERS = {
    # In-scope NC tax-foreclosure counties (wake/forsyth/guilford/durham/
    # mecklenburg dropped 2026-05-14 per scope tightening)
    "counties_nc.new_hanover_tax",
    "counties_nc.buncombe_tax",
    "counties_nc.cleveland_tax",
    "counties_nc.henderson_tax",
    "counties_nc.polk_tax",
    "counties_nc.rutherford_tax",
    "counties_nc.brunswick_tax",
    "counties_nc.nc_rod_substitute_trustee",
    "counties_nc.nc_ecourts_lis_pendens",
    "counties_sc.sc_courtrosters",
    "counties_sc.sc_public_index_lis_pendens",
    "counties_sc.sc_tax_delinquent",
    "counties_sc.spartanburg_master_in_equity",
    "counties_sc.anderson_master_in_equity",
    "counties_sc.pickens_master_in_equity",
    "reo.usda_rd",
    "reo.treasury_seized",
    "reo.vrm_va_reo",
}


async def run_one(slug: str, timeout_s: float = 90.0) -> tuple[str, int, float, str]:
    scraper = next((s for s in all_scrapers() if s.slug == slug), None)
    if scraper is None:
        return slug, 0, 0.0, f"NOT_FOUND in registry"
    t0 = time.monotonic()
    try:
        listings = await asyncio.wait_for(scraper.safe_run(), timeout=timeout_s)
        elapsed = time.monotonic() - t0
        return slug, len(listings), elapsed, "OK" if listings else "EMPTY"
    except asyncio.TimeoutError:
        return slug, 0, timeout_s, f"TIMEOUT_{timeout_s}s"
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        tb = traceback.format_exc().splitlines()[-3:]
        return slug, 0, elapsed, f"ERROR: {type(exc).__name__}: {str(exc)[:200]}"


async def main():
    args = sys.argv[1:]
    if not args:
        print("usage: smoke_one_scraper.py <slug> | --all-free", file=sys.stderr)
        sys.exit(1)

    if args[0] == "--all-free":
        slugs = sorted(FREE_SCRAPERS)
    else:
        slugs = args

    print(f"{'slug':<55} {'count':>6} {'time_s':>7} status")
    print("-" * 100)
    for slug in slugs:
        s, n, t, status = await run_one(slug)
        print(f"{s:<55} {n:>6} {t:>7.1f} {status}")


if __name__ == "__main__":
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    asyncio.run(main())
