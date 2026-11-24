#!/usr/bin/env python3
"""BRUTAL TEST - Run EVERY scraper and see what percentage actually work.

NO SPECULATION. ACTUAL RESULTS ONLY.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.scrapers._registry import discover
import structlog

log = structlog.get_logger()


async def test_scraper(ScraperClass, timeout_s=45):
    """Test one scraper - returns (name, result_count, error_msg)."""
    name = ScraperClass.__name__
    
    try:
        scraper = ScraperClass()
        results = await asyncio.wait_for(scraper.fetch(), timeout=timeout_s)
        return name, len(results), None
        
    except asyncio.TimeoutError:
        return name, 0, f"TIMEOUT ({timeout_s}s)"
        
    except Exception as exc:
        error_msg = str(exc)[:150]
        return name, 0, error_msg


async def test_all_scrapers():
    """Test ALL registered scrapers and show results."""
    
    scrapers = discover()
    print(f"\n{'='*80}")
    print(f"🔥 TESTING ALL {len(scrapers)} SCRAPERS")
    print(f"{'='*80}\n")
    
    # Test all in batches of 10
    batch_size = 10
    all_results = []
    
    for i in range(0, len(scrapers), batch_size):
        batch = scrapers[i:i+batch_size]
        print(f"\n📦 Batch {i//batch_size + 1} ({len(batch)} scrapers)...")
        
        tasks = [test_scraper(S) for S in batch]
        batch_results = await asyncio.gather(*tasks)
        all_results.extend(batch_results)
        
        # Show batch results
        for name, count, error in batch_results:
            if error:
                print(f"  ❌ {name}: {error}")
            elif count == 0:
                print(f"  ⚠️  {name}: 0 results")
            else:
                print(f"  ✅ {name}: {count} results")
    
    # Summary
    print(f"\n{'='*80}")
    print("📊 SUMMARY")
    print(f"{'='*80}\n")
    
    working = [(n, c) for n, c, e in all_results if e is None and c > 0]
    zero_results = [(n, c) for n, c, e in all_results if e is None and c == 0]
    errors = [(n, e) for n, c, e in all_results if e is not None]
    
    total = len(all_results)
    working_pct = len(working) / total * 100 if total else 0
    
    print(f"✅ WORKING ({len(working)}/{total} = {working_pct:.1f}%):")
    for name, count in sorted(working, key=lambda x: -x[1])[:10]:
        print(f"   {name}: {count} results")
    if len(working) > 10:
        print(f"   ... and {len(working) - 10} more")
    
    print(f"\n⚠️  ZERO RESULTS ({len(zero_results)}/{total}):")
    for name, _ in zero_results[:10]:
        print(f"   {name}")
    if len(zero_results) > 10:
        print(f"   ... and {len(zero_results) - 10} more")
    
    print(f"\n❌ ERRORS ({len(errors)}/{total}):")
    for name, error in errors[:10]:
        print(f"   {name}: {error}")
    if len(errors) > 10:
        print(f"   ... and {len(errors) - 10} more")
    
    print(f"\n{'='*80}")
    print(f"BOTTOM LINE: {len(working)}/{total} scrapers actually work ({working_pct:.1f}%)")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(test_all_scrapers())
