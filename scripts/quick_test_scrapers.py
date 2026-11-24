#!/usr/bin/env python3
"""Quick test of high-priority scrapers from spreadsheet"""
import asyncio
import sys
sys.path.insert(0, 'src')

# Key scrapers to test
SCRAPERS = [
    # Already confirmed working
    ("foreclosure_scraper.scrapers.counties_sc.orangeburg_scrod", "OrangeburgSCROD"),
    ("foreclosure_scraper.scrapers.counties_sc.sc_countyfusion_rod", "SCCountyFusionROD"),
    
    # Tax scrapers (69 exist)
    ("foreclosure_scraper.scrapers.counties_nc.bertie_tax", "BertieTax"),
    ("foreclosure_scraper.scrapers.counties_nc.mcdowell_tax", "McDowellTax"),
    ("foreclosure_scraper.scrapers.counties_nc.rutherford_tax", "RutherfordTax"),
    
    # ROD scrapers (16 exist)  
    ("foreclosure_scraper.scrapers.counties_sc.charleston_scrod", "CharlestonSCROD"),
    ("foreclosure_scraper.scrapers.counties_nc.wake_tyler_rod", "WakeTylerROD"),
    
    # Probate (16 exist)
    ("foreclosure_scraper.scrapers.counties_sc.spartanburg_probate", "SpartanburgProbate"),
]


async def test_one(module_path, class_name):
    """Test one scraper."""
    try:
        # Import
        parts = module_path.split('.')
        module = __import__(module_path, fromlist=[class_name])
        scraper_class = getattr(module, class_name)
        
        # Test
        scraper = scraper_class()
        result = await asyncio.wait_for(scraper.fetch(), timeout=60)
        
        # Count
        listings = list(result) if result else []
        return {"name": class_name, "count": len(listings), "status": "ok"}
    
    except asyncio.TimeoutError:
        return {"name": class_name, "count": 0, "status": "timeout"}
    except Exception as e:
        return {"name": class_name, "count": 0, "status": "error", "error": str(e)[:100]}


async def main():
    print("🧪 QUICK SCRAPER TEST")
    print("=" * 70)
    
    results = []
    for i, (module_path, class_name) in enumerate(SCRAPERS, 1):
        print(f"\n[{i}/{len(SCRAPERS)}] {class_name}...", end=" ", flush=True)
        
        result = await test_one(module_path, class_name)
        results.append(result)
        
        if result["status"] == "ok":
            if result["count"] > 0:
                print(f"✅ {result['count']} listings")
            else:
                print(f"⚠️  0 listings")
        elif result["status"] == "timeout":
            print(f"⏱️  TIMEOUT")
        else:
            print(f"❌ {result.get('error', 'Error')[:60]}")
    
    # Summary
    print("\n" + "=" * 70)
    working = [r for r in results if r["status"] == "ok" and r["count"] > 0]
    empty = [r for r in results if r["status"] == "ok" and r["count"] == 0]
    failed = [r for r in results if r["status"] != "ok"]
    
    print(f"\n✅ Working: {len(working)}/{len(results)}")
    for r in working:
        print(f"   {r['name']}: {r['count']} listings")
    
    print(f"\n⚠️  Empty: {len(empty)}")
    print(f"❌ Failed: {len(failed)}")


if __name__ == "__main__":
    asyncio.run(main())
