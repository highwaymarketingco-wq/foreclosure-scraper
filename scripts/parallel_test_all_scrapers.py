#!/usr/bin/env python3
"""
PARALLEL scraper testing - run 5 at a time with 60s timeout each.

This will test all 296 scrapers in ~1 hour instead of 5+ hours.
"""
import asyncio
import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.base_scraper import BaseScraper


async def test_scraper(scraper_class, timeout=60) -> dict:
    """Test one scraper with timeout."""
    result = {
        "name": scraper_class.__name__,
        "slug": getattr(scraper_class, 'slug', 'unknown'),
        "status": "unknown",
        "count": 0,
        "error": None,
    }
    
    try:
        scraper = scraper_class()
        listings = await asyncio.wait_for(scraper.fetch(), timeout=timeout)
        
        # Convert to list
        if hasattr(listings, '__aiter__'):
            count = 0
            async for _ in listings:
                count += 1
                if count >= 10000:  # Cap to avoid memory issues
                    break
            result["count"] = count
        elif listings:
            result["count"] = len(list(listings))
        
        result["status"] = "success" if result["count"] > 0 else "empty"
    
    except asyncio.TimeoutError:
        result["status"] = "timeout"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
    
    return result


async def main():
    """Test all scrapers in parallel batches."""
    
    print("🚀 PARALLEL SCRAPER TESTING")
    print("=" * 70)
    
    # Discover all scrapers
    import importlib.util
    
    scrapers_dir = Path(__file__).parent.parent / "src" / "foreclosure_scraper" / "scrapers"
    all_scrapers = []
    
    for py_file in scrapers_dir.rglob("*.py"):
        if py_file.name.startswith("_") or py_file.name == "base_scraper.py":
            continue
        
        try:
            module_path = py_file.relative_to(scrapers_dir.parent)
            module_name = str(module_path.with_suffix("")).replace("/", ".")
            
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if not spec or not spec.loader:
                continue
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseScraper) and attr is not BaseScraper:
                    if not any(s.__name__ == attr.__name__ for s in all_scrapers):
                        all_scrapers.append(attr)
        except Exception:
            continue
    
    print(f"\nFound {len(all_scrapers)} scrapers")
    print(f"Testing in parallel batches of 5 with 60s timeout each\n")
    
    results = []
    batch_size = 5
    
    for i in range(0, len(all_scrapers), batch_size):
        batch = all_scrapers[i:i+batch_size]
        
        print(f"📦 Batch {i//batch_size + 1} ({i+1}-{min(i+batch_size, len(all_scrapers))}/{len(all_scrapers)})")
        
        # Run batch in parallel
        tasks = [test_scraper(scraper_class) for scraper_class in batch]
        batch_results = await asyncio.gather(*tasks)
        
        # Print results
        for result in batch_results:
            results.append(result)
            name = result['name']
            
            if result['status'] == 'success':
                print(f"  ✅ {name}: {result['count']} listings")
            elif result['status'] == 'empty':
                print(f"  ⚠️  {name}: 0 listings")
            elif result['status'] == 'timeout':
                print(f"  ⏱️  {name}: TIMEOUT")
            else:
                print(f"  ❌ {name}: {result.get('error', 'Error')[:60]}")
        
        # Save progress
        output_file = Path(__file__).parent.parent / "docs" / "scraper_test_results.json"
        output_file.write_text(json.dumps(results, indent=2))
    
    # Final summary
    print("\n" + "=" * 70)
    print("🎯 FINAL RESULTS")
    print("=" * 70)
    
    success = [r for r in results if r["status"] == "success"]
    empty = [r for r in results if r["status"] == "empty"]
    errors = [r for r in results if r["status"] == "error"]
    timeouts = [r for r in results if r["status"] == "timeout"]
    
    print(f"\n✅ Success: {len(success)}")
    print(f"⚠️  Empty: {len(empty)}")
    print(f"❌ Errors: {len(errors)}")
    print(f"⏱️  Timeouts: {len(timeouts)}")
    
    print(f"\n📊 Top 20 working scrapers:")
    for r in sorted(success, key=lambda x: x['count'], reverse=True)[:20]:
        print(f"   {r['name']}: {r['count']} listings")
    
    print(f"\n🎯 Success rate: {len(success)}/{len(results)} = {len(success)*100//len(results) if results else 0}%")


if __name__ == "__main__":
    asyncio.run(main())
