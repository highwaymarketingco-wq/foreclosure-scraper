#!/usr/bin/env python3
"""Read-only diagnostic sweep across every national.jail_bookings ROSTERS
entry -- reports per-county row counts so any OTHER Sumter/Hertford-style
silent-zero-row entry surfaces in one pass instead of hand-checking comments.
Writes nothing to the board; just prints a report.

Usage: python scripts/diag_jail_bookings_rosters.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.scrapers.national.jail_bookings import ROSTERS, _fetch_roster  # noqa: E402


async def main() -> int:
    t0 = time.monotonic()
    tasks = [_fetch_roster(state, county, vendor, target) for state, county, vendor, target in ROSTERS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    zero: list[str] = []
    errored: list[str] = []
    ok: list[tuple[str, int]] = []
    for (state, county, vendor, target), res in zip(ROSTERS, results):
        label = f"{state}/{county} ({vendor})"
        if isinstance(res, Exception):
            errored.append(f"{label}: {type(res).__name__}: {str(res)[:120]}")
            continue
        n = len(res or [])
        if n == 0:
            zero.append(label)
        else:
            ok.append((label, n))

    print(f"=== {len(ROSTERS)} counties swept in {time.monotonic() - t0:.1f}s ===")
    print(f"OK (non-zero): {len(ok)}")
    for label, n in sorted(ok, key=lambda x: -x[1]):
        print(f"  {label}: {n}")
    print(f"\nZERO ROWS: {len(zero)}")
    for label in zero:
        print(f"  {label}")
    print(f"\nERRORED: {len(errored)}")
    for label in errored:
        print(f"  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
