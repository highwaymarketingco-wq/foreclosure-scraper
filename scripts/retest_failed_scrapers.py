#!/usr/bin/env python3
"""
RETEST failed/timeout scrapers with LONGER timeout (300s) and fixes.

Targets:
- 20 timeout scrapers (90s → 300s)
- 1 error scraper (403 - needs investigation)
"""
import asyncio
import sys
from pathlib import Path
import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.base_scraper import BaseScraper


# Load previous results to find failed scrapers
def load_failed_scrapers():
    """Load scrapers that timed out or errored from previous test."""
    results_file = Path(__file__).parent.parent / "docs" / "scraper_test_results.json"
    
    if not results_file.exists():
        print("❌ No previous results found")
        return [], []
    
    with open(results_file) as f:
        results = json.load(f)
    
    timeouts = [r["name"] for r in results if r["status"] == "timeout"]
    errors = [r["name"] for r in results if r["status"] == "error"]
    
    print(f"📋 Found {len(timeouts)} timeouts, {len(errors)} errors")
    return timeouts, errors


def discover_scrapers_by_name(target_names):
    """Discover specific scrapers by class name."""
    scrapers_dir = Path(__file__).parent.parent / "src" / "foreclosure_scraper" / "scrapers"
    
    discovered = {}
    
    for py_file in scrapers_dir.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        
        rel_path = py_file.relative_to(scrapers_dir.parent)
        module_name = str(rel_path.with_suffix("")).replace("/", ".")
        
        if not module_name.startswith("foreclosure_scraper"):
            module_name = "foreclosure_scraper." + module_name
        
        try:
            module = __import__(module_name, fromlist=["*"])
            
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BaseScraper) and 
                    attr is not BaseScraper and
                    attr.__name__ in target_names):
                    discovered[attr.__name__] = attr
        
        except Exception:
            pass
    
    return discovered


async def test_scraper(scraper_class, timeout=300):
    """Test a single scraper with extended timeout."""
    try:
        scraper = scraper_class()
        
        # Check if fetch is async or sync
        fetch_method = scraper.fetch()
        
        if asyncio.iscoroutine(fetch_method):
            # Async scraper
            result = await asyncio.wait_for(fetch_method, timeout=timeout)
            result = list(result)  # Convert generator to list if needed
        else:
            # Sync scraper - run in thread
            result = await asyncio.wait_for(
                asyncio.to_thread(lambda: list(fetch_method)),
                timeout=timeout
            )
        
        return {
            "status": "success",
            "name": scraper_class.__name__,
            "count": len(result),
        }
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "name": scraper_class.__name__,
            "timeout": timeout,
        }
    except Exception as e:
        return {
            "status": "error",
            "name": scraper_class.__name__,
            "error": str(e)[:200],
        }


async def main():
    print("🔄 RETEST FAILED SCRAPERS")
    print("=" * 70)
    
    # Load failed scrapers from previous run
    timeouts, errors = load_failed_scrapers()
    all_failed = timeouts + errors
    
    if not all_failed:
        print("❌ No failed scrapers to retest")
        return
    
    print(f"\n🎯 Retesting {len(all_failed)} scrapers with 300s timeout")
    print()
    
    # Discover the scraper classes
    discovered = discover_scrapers_by_name(all_failed)
    print(f"✅ Found {len(discovered)} scraper classes to retest\n")
    
    missing = set(all_failed) - set(discovered.keys())
    if missing:
        print(f"⚠️  Could not find: {', '.join(list(missing)[:5])}...")
        print()
    
    # Test in batches of 3 (slower scrapers)
    results = []
    batch_size = 3
    scrapers_list = list(discovered.items())
    
    for i in range(0, len(scrapers_list), batch_size):
        batch = scrapers_list[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(scrapers_list) + batch_size - 1) // batch_size
        
        print(f"📦 Batch {batch_num}/{total_batches} ({i+1}-{min(i+batch_size, len(scrapers_list))}/{len(scrapers_list)})")
        
        # Run batch in parallel
        tasks = [test_scraper(cls, timeout=300) for name, cls in batch]
        batch_results = await asyncio.gather(*tasks)
        
        # Print results
        for result in batch_results:
            if result["status"] == "success":
                print(f"  ✅ {result['name']}: {result['count']} listings")
            elif result["status"] == "timeout":
                print(f"  ⏱️  {result['name']}: TIMEOUT (300s)")
            else:
                print(f"  ❌ {result['name']}: {result['error'][:80]}")
        
        results.extend(batch_results)
        print()
    
    # Save results
    output_file = Path(__file__).parent.parent / "docs" / "retest_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    # Summary
    success = [r for r in results if r["status"] == "success"]
    still_timeout = [r for r in results if r["status"] == "timeout"]
    still_error = [r for r in results if r["status"] == "error"]
    
    print("=" * 70)
    print("🎯 RETEST RESULTS")
    print("=" * 70)
    print(f"✅ Now working: {len(success)}")
    print(f"⏱️  Still timeout: {len(still_timeout)}")
    print(f"❌ Still errors: {len(still_error)}")
    
    if success:
        total_new = sum(r["count"] for r in success)
        print(f"\n🎉 RESCUED {len(success)} scrapers = {total_new:,} NEW listings!")
        print("\nTop rescued:")
        for r in sorted(success, key=lambda x: x["count"], reverse=True)[:10]:
            print(f"  - {r['name']}: {r['count']:,} listings")
    
    print(f"\n💾 Saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
