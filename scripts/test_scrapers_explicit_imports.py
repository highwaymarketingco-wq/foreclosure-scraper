#!/usr/bin/env python3
"""
Test scrapers with EXPLICIT imports and FULL error logging.

No more silent failures - log every import attempt.

MUST run with: PYTHONPATH=src .venv/bin/python (uses venv dependencies)
"""
import asyncio
import sys
from pathlib import Path
import json
from datetime import datetime

# Ensure we're using the src path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.base_scraper import BaseScraper


def discover_scrapers_with_logging():
    """Discover scrapers by listing files and importing each one."""
    scrapers_dir = Path(__file__).parent.parent / "src" / "foreclosure_scraper" / "scrapers"
    
    all_files = list(scrapers_dir.rglob("*.py"))
    scraper_files = [f for f in all_files if not f.name.startswith("_")]
    
    print(f"Found {len(scraper_files)} Python files")
    print(f"Attempting to import each one...\n")
    
    discovered = []
    failed_imports = []
    
    for py_file in sorted(scraper_files):
        rel_path = py_file.relative_to(scrapers_dir.parent)
        module_name = str(rel_path.with_suffix("")).replace("/", ".")
        
        # Skip if not under foreclosure_scraper
        if not module_name.startswith("foreclosure_scraper"):
            module_name = "foreclosure_scraper." + module_name
        
        try:
            # Import the module
            module = __import__(module_name, fromlist=["*"])
            
            # Find BaseScraper subclasses
            found_in_module = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BaseScraper) and 
                    attr is not BaseScraper):
                    found_in_module.append(attr)
            
            if found_in_module:
                for scraper_class in found_in_module:
                    # Avoid duplicates
                    if not any(s.__name__ == scraper_class.__name__ for s in discovered):
                        discovered.append(scraper_class)
                        print(f"✅ {scraper_class.__name__} ({py_file.name})")
        
        except Exception as e:
            error_msg = str(e)
            failed_imports.append({"file": py_file.name, "error": error_msg[:200]})
            # Only print first 10 errors to avoid spam
            if len(failed_imports) <= 10:
                print(f"❌ {py_file.name}: {error_msg[:100]}")
    
    print(f"\n{'='*70}")
    print(f"✅ Successfully imported: {len(discovered)} scrapers")
    print(f"❌ Failed imports: {len(failed_imports)}")
    
    if failed_imports:
        print(f"\nTop 10 import failures:")
        for fail in failed_imports[:10]:
            print(f"  - {fail['file']}: {fail['error'][:80]}")
    
    return discovered


async def test_scraper(scraper_class, timeout=90) -> dict:
    """Test one scraper."""
    result = {
        "name": scraper_class.__name__,
        "slug": getattr(scraper_class, 'slug', 'unknown'),
        "status": "unknown",
        "count": 0,
        "error": None,
        "time": 0,
    }
    
    start = datetime.now()
    
    try:
        scraper = scraper_class()
        listings = await asyncio.wait_for(scraper.fetch(), timeout=timeout)
        
        # Count results
        if hasattr(listings, '__aiter__'):
            count = 0
            async for _ in listings:
                count += 1
                if count >= 50000:  # Cap at 50k to avoid memory issues
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
    
    result["time"] = (datetime.now() - start).total_seconds()
    return result


async def main():
    """Discover and test all scrapers."""
    
    print("🔍 SCRAPER DISCOVERY WITH FULL ERROR LOGGING")
    print("=" * 70)
    print()
    
    # Discover scrapers with logging
    scrapers = discover_scrapers_with_logging()
    
    if not scrapers:
        print("\n❌ No scrapers discovered - check import errors above")
        return
    
    print(f"\n{'='*70}")
    print("🧪 TESTING DISCOVERED SCRAPERS")
    print("=" * 70)
    
    results = []
    batch_size = 5
    
    for i in range(0, len(scrapers), batch_size):
        batch = scrapers[i:i+batch_size]
        
        print(f"\n📦 Batch {i//batch_size + 1} ({i+1}-{min(i+batch_size, len(scrapers))}/{len(scrapers)})")
        
        # Test in parallel
        tasks = [test_scraper(sc) for sc in batch]
        batch_results = await asyncio.gather(*tasks)
        
        for result in batch_results:
            results.append(result)
            name = result['name']
            
            if result['status'] == 'success':
                print(f"  ✅ {name}: {result['count']:,} listings ({result['time']:.1f}s)")
            elif result['status'] == 'empty':
                print(f"  ⚠️  {name}: 0 listings ({result['time']:.1f}s)")
            elif result['status'] == 'timeout':
                print(f"  ⏱️  {name}: TIMEOUT (90s)")
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
    
    if success:
        print(f"\n📊 Top 30 working scrapers:")
        for r in sorted(success, key=lambda x: x['count'], reverse=True)[:30]:
            print(f"   {r['name']}: {r['count']:,} listings")
    
    total_listings = sum(r['count'] for r in success)
    print(f"\n🎯 Total listings: {total_listings:,}")
    print(f"🎯 Success rate: {len(success)}/{len(results)} = {len(success)*100//len(results) if results else 0}%")


if __name__ == "__main__":
    asyncio.run(main())
