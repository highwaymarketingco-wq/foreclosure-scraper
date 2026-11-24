#!/usr/bin/env python3
"""
Production test sweep: Run ALL 294 scrapers and report which return data.

This discovers your ACTUAL coverage of the 1.1M row spreadsheet.
Runs each scraper with 60s timeout, reports success/failure/count.
"""
import asyncio
import sys
import importlib
import inspect
from pathlib import Path
from datetime import datetime
import json

sys.path.insert(0, 'src')

# Track results
RESULTS = {
    "working": [],
    "empty": [],
    "failed": [],
    "timeout": [],
}

async def test_scraper(module_name: str, class_name: str, timeout: int = 60):
    """Test one scraper"""
    try:
        # Import
        mod = importlib.import_module(module_name)
        ScraperClass = getattr(mod, class_name)
        scraper = ScraperClass()
        
        # Fetch with timeout
        listings_iter = await asyncio.wait_for(scraper.fetch(), timeout=timeout)
        listings = list(listings_iter) if listings_iter else []
        
        return {
            "status": "working" if listings else "empty",
            "count": len(listings),
            "error": None,
        }
        
    except asyncio.TimeoutError:
        return {"status": "timeout", "count": 0, "error": "Timeout"}
    except Exception as e:
        return {"status": "failed", "count": 0, "error": str(e)[:100]}

def find_all_scrapers():
    """Find all scraper classes"""
    scrapers = []
    base_path = Path("src/foreclosure_scraper/scrapers")
    
    for py_file in base_path.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
            
        rel_path = py_file.relative_to("src")
        module_name = str(rel_path.with_suffix("")).replace("/", ".")
        
        try:
            mod = importlib.import_module(module_name)
            
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if name != "BaseScraper" and hasattr(obj, "fetch"):
                    scrapers.append({
                        "module": module_name,
                        "class": name,
                        "file": str(py_file),
                    })
        except:
            continue
    
    return scrapers

async def main():
    print("🧪 PRODUCTION TEST SWEEP - Testing ALL 294 scrapers")
    print("=" * 70)
    print()
    
    scrapers = find_all_scrapers()
    total = len(scrapers)
    
    print(f"Found {total} scrapers")
    print(f"Testing each with 60s timeout...")
    print()
    
    for idx, scraper_info in enumerate(scrapers, 1):
        module = scraper_info["module"]
        cls = scraper_info["class"]
        
        print(f"[{idx}/{total}] {cls}... ", end="", flush=True)
        
        result = await test_scraper(module, cls)
        status = result["status"]
        count = result["count"]
        
        if status == "working":
            print(f"✅ {count} listings")
            RESULTS["working"].append({
                "class": cls,
                "module": module,
                "count": count,
            })
        elif status == "empty":
            print(f"⚠️  0 listings")
            RESULTS["empty"].append({"class": cls, "module": module})
        elif status == "timeout":
            print(f"⏱️  timeout")
            RESULTS["timeout"].append({"class": cls, "module": module})
        else:
            print(f"❌ {result['error'][:40]}")
            RESULTS["failed"].append({
                "class": cls,
                "module": module,
                "error": result["error"],
            })
        
        # Brief pause between tests
        await asyncio.sleep(0.5)
    
    # Summary
    print()
    print("=" * 70)
    print("📊 FINAL RESULTS")
    print("=" * 70)
    print()
    
    working_count = len(RESULTS["working"])
    empty_count = len(RESULTS["empty"])
    failed_count = len(RESULTS["failed"])
    timeout_count = len(RESULTS["timeout"])
    
    print(f"✅ WORKING ({working_count} scrapers returned data):")
    total_listings = 0
    for s in sorted(RESULTS["working"], key=lambda x: x["count"], reverse=True)[:20]:
        print(f"   {s['class']}: {s['count']} listings")
        total_listings += s["count"]
    if working_count > 20:
        print(f"   ... and {working_count - 20} more")
    
    print(f"\n   TOTAL LISTINGS: {total_listings:,}")
    
    print(f"\n⚠️  EMPTY ({empty_count} scrapers ran but returned 0):")
    for s in RESULTS["empty"][:10]:
        print(f"   {s['class']}")
    if empty_count > 10:
        print(f"   ... and {empty_count - 10} more")
    
    print(f"\n❌ FAILED ({failed_count} scrapers errored):")
    for s in RESULTS["failed"][:10]:
        print(f"   {s['class']}: {s['error'][:50]}")
    if failed_count > 10:
        print(f"   ... and {failed_count - 10} more")
    
    if timeout_count:
        print(f"\n⏱️  TIMEOUT ({timeout_count} scrapers timed out)")
    
    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_scrapers": total,
        "working": RESULTS["working"],
        "empty": RESULTS["empty"],
        "failed": RESULTS["failed"],
        "timeout": RESULTS["timeout"],
        "summary": {
            "working_count": working_count,
            "empty_count": empty_count,
            "failed_count": failed_count,
            "timeout_count": timeout_count,
            "total_listings": total_listings,
        }
    }
    
    output_path = "docs/production_test_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\n💾 Full results saved to {output_path}")
    print()
    print(f"📈 SUCCESS RATE: {working_count}/{total} ({working_count/total*100:.1f}%)")

if __name__ == "__main__":
    asyncio.run(main())
