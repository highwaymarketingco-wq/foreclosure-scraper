#!/usr/bin/env python3
"""Test every registered scraper's fetch() method with a per-scraper timeout.
Writes results to /tmp/scraper_test_results.json"""
import asyncio
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

# Set up paths
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/.venv/lib/python3.12/site-packages")

from foreclosure_scraper.scrapers._registry import all_scrapers


async def _collect_fetch(s):
    """Consume fetch() whether it returns a list or is an async generator."""
    result = s.fetch()
    # Check if it's an async generator (has __aiter__)
    if hasattr(result, "__aiter__"):
        return [li async for li in result]
    # Otherwise it's a coroutine — await it
    awaited = await result
    return list(awaited) if awaited else []


async def _probe_one(s, timeout_s=30):
    slug = getattr(s, "source", type(s).__name__)
    try:
        listings = await asyncio.wait_for(_collect_fetch(s), timeout=timeout_s)
        return {"slug": slug, "count": len(listings), "error": None}
    except asyncio.TimeoutError:
        return {"slug": slug, "count": 0, "error": "TIMEOUT"}
    except Exception as e:
        tb = traceback.format_exc()[-300:]
        return {"slug": slug, "count": 0, "error": str(e)[:300] + " | " + tb}


async def main():
    scrapers = all_scrapers()
    print(f"Testing {len(scrapers)} scrapers with 30s timeout each...", flush=True)

    results = []
    for i, s in enumerate(scrapers):
        slug = getattr(s, "source", type(s).__name__)
        r = await _probe_one(s)
        results.append(r)
        status = "OK" if r["count"] > 0 else ("ERR" if r["error"] else "ZERO")
        if status == "OK":
            print(f"[{i+1}/{len(scrapers)}] OK   {r['slug']}: {r['count']} listings", flush=True)
        elif status == "ERR":
            err_short = r["error"][:120] if r["error"] else ""
            print(f"[{i+1}/{len(scrapers)}] ERR  {r['slug']}: {err_short}", flush=True)
        else:
            print(f"[{i+1}/{len(scrapers)}] ZERO {r['slug']}", flush=True)

    producing = [r for r in results if r["count"] > 0]
    zero = [r for r in results if r["count"] == 0 and not r["error"]]
    errored = [r for r in results if r["error"]]

    print(f"\n=== SUMMARY ===", flush=True)
    print(f"Total: {len(results)}", flush=True)
    print(f"Producing: {len(producing)}", flush=True)
    print(f"Zero (no error): {len(zero)}", flush=True)
    print(f"Errored: {len(errored)}", flush=True)

    if errored:
        print(f"\n=== ERRORED SCRAPERS ===", flush=True)
        for r in errored:
            print(f"  {r['slug']}: {r['error'][:200]}", flush=True)

    with open("/tmp/scraper_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to /tmp/scraper_test_results.json", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
