"""Run a single scraper with verbose logs + full traceback.

usage:
  uv run python scripts/diagnose_one.py <slug>
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("LOG_LEVEL", "DEBUG")

import structlog

from foreclosure_scraper.scrapers._registry import all_scrapers


async def run(slug: str, timeout_s: float = 120.0):
    scraper = next((s for s in all_scrapers() if s.slug == slug), None)
    if scraper is None:
        print(f"NOT FOUND: {slug}")
        return
    print(f"=== {slug} === class={type(scraper).__name__} module={type(scraper).__module__}")
    t0 = time.monotonic()
    try:
        listings = await asyncio.wait_for(scraper.safe_run(), timeout=timeout_s)
        dt = time.monotonic() - t0
        print(f"--- RESULT: count={len(listings)} time={dt:.1f}s ---")
        if listings:
            li = listings[0]
            print(f"--- sample first listing ---")
            print(f"case={li.case_number} county={li.county} addr={li.street_address}")
            print(f"raw_keys={sorted((li.raw or {}).keys())[:20]}")
    except asyncio.TimeoutError:
        print(f"--- TIMEOUT after {timeout_s}s ---")
    except Exception:
        print(f"--- EXCEPTION ---")
        traceback.print_exc()


def main():
    if len(sys.argv) < 2:
        print("usage: diagnose_one.py <slug>", file=sys.stderr)
        sys.exit(1)
    logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    )
    asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    main()
