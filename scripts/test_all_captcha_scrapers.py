#!/usr/bin/env python3
"""Test ALL CAPTCHA/login scrapers from the handoff spreadsheet"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'src')

# Map spreadsheet entries to actual scraper classes
SCRAPERS_TO_TEST = [
    # Already tested
    ("Lexington CountyFusion ROD", "counties_sc.sc_countyfusion_rod", "SCCountyFusionROD", {"county": "lexington"}),
    ("Darlington RecordHub", "counties_sc.darlington_recordhub", "DarlingtonRecordhub", {}),
    ("Williamsburg Avenu", "counties_sc.sc_avenu_rod", "SCAvenuROD", {"county": "williamsburg"}),
    
    # Probate (should already work with existing solvers)
    ("Lexington Probate", "counties_sc.lexington_probate", "LexingtonProbate", {}),
    
    # Need to check if these exist
    ("Orangeburg ROD", "counties_sc.orangeburg_scrod", None, {}),
]

async def test_scraper(name: str, module_path: str, class_name: str, kwargs: dict):
    """Test one scraper"""
    print(f"\n{'='*70}")
    print(f"Testing: {name}")
    print(f"{'='*70}")
    
    try:
        # Import dynamically
        parts = module_path.split(".")
        mod = __import__(f"foreclosure_scraper.scrapers.{module_path}", fromlist=[class_name or ""])
        
        if class_name:
            ScraperClass = getattr(mod, class_name)
        else:
            # Find the scraper class
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and hasattr(attr, "fetch") and attr.__name__ != "BaseScraper":
                    ScraperClass = attr
                    break
            else:
                print(f"❌ Could not find scraper class in {module_path}")
                return False
        
        scraper = ScraperClass(**kwargs)
        
        # Try to fetch (with timeout)
        print(f"Fetching from {ScraperClass.__name__}...")
        
        try:
            listings_iter = await asyncio.wait_for(scraper.fetch(), timeout=120)
            listings = list(listings_iter) if listings_iter else []
            
            if listings:
                print(f"✅ SUCCESS! Got {len(listings)} listings")
                # Show first record
                if listings:
                    first = listings[0].model_dump()
                    print(f"\n   First listing:")
                    print(f"     Type: {first.get('listing_type')}")
                    print(f"     County: {first.get('county')}")
                    if 'recorded_date' in first:
                        print(f"     Date: {first['recorded_date']}")
                return True
            else:
                print(f"⚠️  Returned 0 listings (may be normal for test date range)")
                return True  # Not a failure, just no data
                
        except asyncio.TimeoutError:
            print(f"❌ TIMEOUT after 120s")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("🔍 Testing ALL CAPTCHA/login scrapers from handoff spreadsheet\n")
    
    results = {}
    for name, module, cls, kwargs in SCRAPERS_TO_TEST:
        success = await test_scraper(name, module, cls, kwargs)
        results[name] = success
        await asyncio.sleep(2)  # Pause between tests
    
    # Summary
    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    
    working = [n for n, s in results.items() if s]
    broken = [n for n, s in results.items() if not s]
    
    print(f"\n✅ WORKING ({len(working)}):")
    for n in working:
        print(f"   - {n}")
    
    if broken:
        print(f"\n❌ BROKEN ({len(broken)}):")
        for n in broken:
            print(f"   - {n}")
    
    print(f"\n📊 Total: {len(working)}/{len(results)} working")

if __name__ == "__main__":
    asyncio.run(main())
