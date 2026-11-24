#!/usr/bin/env python3
"""Quick test: run 20 random scrapers and see success rate."""
import asyncio
import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.scrapers._registry import discover


async def quick_test(ScraperClass, timeout=30):
    """Test one scraper quickly."""
    name = ScraperClass.__name__
    try:
        scraper = ScraperClass()
        results = await asyncio.wait_for(scraper.fetch(), timeout=timeout)
        return name, len(results), None
    except asyncio.TimeoutError:
        return name, -1, "TIMEOUT"
    except Exception as exc:
        return name, -1, str(exc)[:80]


async def main():
    all_scrapers = discover()
    print(f"Found {len(all_scrapers)} total scrapers")
    
    # Test 20 random ones
    sample = random.sample(all_scrapers, min(20, len(all_scrapers)))
    
    print("\n🔥 TESTING 20 RANDOM SCRAPERS...\n")
    
    tasks = [quick_test(S) for S in sample]
    results = await asyncio.gather(*tasks)
    
    working = [(n, c) for n, c, e in results if e is None and c > 0]
    zero = [(n, c) for n, c, e in results if e is None and c == 0]
    failed = [(n, e) for n, c, e in results if e is not None]
    
    print(f"\n{'='*80}")
    print(f"RESULTS:")
    print(f"  ✅ Working: {len(working)}/20")
    print(f"  ⚠️  Zero results: {len(zero)}/20")
    print(f"  ❌ Failed: {len(failed)}/20")
    print(f"{'='*80}\n")
    
    if working:
        print("✅ WORKING:")
        for name, count in working:
            print(f"   {name}: {count} results")
    
    if failed:
        print("\n❌ FAILED:")
        for name, error in failed[:5]:
            print(f"   {name}: {error}")


if __name__ == "__main__":
    asyncio.run(main())
