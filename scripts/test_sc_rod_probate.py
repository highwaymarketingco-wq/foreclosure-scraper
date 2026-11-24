#!/usr/bin/env python3
"""Test ALL existing SC ROD and probate scrapers"""
import asyncio
import sys
sys.path.insert(0, 'src')

# SC ROD/Probate scrapers that exist
SCRAPERS = [
    # ROD
    ("foreclosure_scraper.scrapers.counties_sc.cherokee_rod", "CherokeeROD"),
    ("foreclosure_scraper.scrapers.counties_sc.sc_rod_acclaim", "SCRODAcclaim"),
    ("foreclosure_scraper.scrapers.counties_sc.sc_rod_cott", "SCRODCott"),
    
    # Probate
    ("foreclosure_scraper.scrapers.counties_sc.greenville_probate", "GreenvilleProbate"),
    ("foreclosure_scraper.scrapers.counties_sc.horry_probate", "HorryProbate"),
    ("foreclosure_scraper.scrapers.counties_sc.sc_richland_probate", "SCRichlandProbate"),
    ("foreclosure_scraper.scrapers.counties_sc.sc_probate_net", "SCProbateNet"),
    ("foreclosure_scraper.scrapers.counties_sc.sc_probate_notices", "SCProbateNotices"),
]


async def test_one(module_path, class_name):
    """Test one scraper."""
    try:
        module = __import__(module_path, fromlist=[class_name])
        scraper_class = getattr(module, class_name)
        
        scraper = scraper_class()
        result = await asyncio.wait_for(scraper.fetch(), timeout=90)
        
        listings = list(result) if result else []
        return {"name": class_name, "count": len(listings), "status": "ok"}
    
    except asyncio.TimeoutError:
        return {"name": class_name, "count": 0, "status": "timeout"}
    except Exception as e:
        return {"name": class_name, "count": 0, "status": "error", "error": str(e)[:150]}


async def main():
    print("🧪 TESTING SC ROD & PROBATE SCRAPERS")
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
            print(f"⏱️  TIMEOUT (90s)")
        else:
            print(f"❌ {result.get('error', 'Error')}")
    
    # Summary
    print("\n" + "=" * 70)
    working = [r for r in results if r["status"] == "ok" and r["count"] > 0]
    empty = [r for r in results if r["status"] == "ok" and r["count"] == 0]
    failed = [r for r in results if r["status"] != "ok"]
    
    print(f"\n✅ Working ({len(working)}):")
    for r in working:
        print(f"   {r['name']}: {r['count']} listings")
    
    print(f"\n⚠️  Empty ({len(empty)}):")
    for r in empty:
        print(f"   {r['name']}")
    
    print(f"\n❌ Failed ({len(failed)}):")
    for r in failed:
        error_preview = r.get('error', r['status'])[:80]
        print(f"   {r['name']}: {error_preview}")
    
    print(f"\n📊 Success rate: {len(working)}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
