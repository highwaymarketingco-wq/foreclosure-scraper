#!/usr/bin/env python3
"""
Systematically test ALL scrapers in order of impact.

Tests each scraper with a 60s timeout, logs results, commits after each batch.
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import after path setup
from foreclosure_scraper.base_scraper import BaseScraper


async def test_scraper(scraper_class) -> dict:
    """Test one scraper, return result dict."""
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
        
        # Run with timeout
        listings = await asyncio.wait_for(scraper.fetch(), timeout=60)
        
        # Convert to list if needed
        if hasattr(listings, '__aiter__'):
            listings = [l async for l in listings]
        elif not isinstance(listings, list):
            listings = list(listings) if listings else []
        
        result["count"] = len(listings)
        result["status"] = "success" if listings else "empty"
        
        if listings:
            # Sample first listing
            first = listings[0].model_dump()
            result["sample"] = {
                "type": first.get("listing_type"),
                "county": first.get("county"),
                "address": first.get("address", "")[:50],
            }
    
    except asyncio.TimeoutError:
        result["status"] = "timeout"
        result["error"] = "60s timeout"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
    
    result["time"] = (datetime.now() - start).total_seconds()
    return result


async def main():
    """Test all scrapers systematically."""
    
    print("🧪 SYSTEMATIC SCRAPER TESTING")
    print("=" * 70)
    
    # Get all scraper classes by scanning the directory
    from pathlib import Path
    import importlib.util
    
    scrapers_dir = Path(__file__).parent.parent / "src" / "foreclosure_scraper" / "scrapers"
    all_scrapers = []
    
    for py_file in scrapers_dir.rglob("*.py"):
        if py_file.name.startswith("_") or py_file.name == "base_scraper.py":
            continue
        
        # Try to import and find BaseScraper subclasses
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
                    # Avoid duplicates
                    if not any(s.__name__ == attr.__name__ for s in all_scrapers):
                        all_scrapers.append(attr)
        except Exception:
            continue
    
    print(f"\nFound {len(all_scrapers)} scrapers to test\n")
    
    if not all_scrapers:
        print("❌ No scrapers found!")
        return
    
    # Test in batches
    results = []
    batch_size = 10
    
    for i in range(0, len(all_scrapers), batch_size):
        batch = all_scrapers[i:i+batch_size]
        
        print(f"\n📦 BATCH {i//batch_size + 1} ({i+1}-{min(i+batch_size, len(all_scrapers))}/{len(all_scrapers)})")
        print("-" * 70)
        
        for scraper_class in batch:
            name = scraper_class.__name__
            print(f"\n[{len(results)+1}/{len(all_scrapers)}] {name}...", end=" ", flush=True)
            
            result = await test_scraper(scraper_class)
            results.append(result)
            
            # Print result
            if result["status"] == "success":
                print(f"✅ {result['count']} listings ({result['time']:.1f}s)")
            elif result["status"] == "empty":
                print(f"⚠️  0 listings ({result['time']:.1f}s)")
            elif result["status"] == "timeout":
                print(f"⏱️  TIMEOUT")
            else:
                print(f"❌ {result['error'][:80]}")
        
        # Save progress after each batch
        output_file = Path(__file__).parent.parent / "docs" / "scraper_test_results.json"
        output_file.write_text(json.dumps(results, indent=2))
        print(f"\n💾 Progress saved ({len(results)} scrapers tested)")
    
    # Final summary
    print("\n" + "=" * 70)
    print("🎯 FINAL RESULTS")
    print("=" * 70)
    
    success = [r for r in results if r["status"] == "success"]
    empty = [r for r in results if r["status"] == "empty"]
    errors = [r for r in results if r["status"] == "error"]
    timeouts = [r for r in results if r["status"] == "timeout"]
    
    print(f"\n✅ Success (returned data): {len(success)}")
    print(f"⚠️  Empty (ran but 0 results): {len(empty)}")
    print(f"❌ Errors: {len(errors)}")
    print(f"⏱️  Timeouts: {len(timeouts)}")
    
    print(f"\n📊 Working scrapers ({len(success)}):")
    for r in sorted(success, key=lambda x: x['count'], reverse=True)[:20]:
        print(f"   {r['name']}: {r['count']} listings")
    
    print(f"\n🎯 Success rate: {len(success)}/{len(results)} = {len(success)*100//len(results) if results else 0}%")


if __name__ == "__main__":
    asyncio.run(main())
