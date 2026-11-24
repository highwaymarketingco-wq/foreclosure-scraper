#!/usr/bin/env python3
"""Quick verification of top 10 scrapers from spreadsheet"""
import asyncio
import sys
import os
sys.path.insert(0, 'src')

# Set Gemini keys
os.environ['GEMINI_API_KEY_1'] = open('.secrets/gemini_api_key_1.txt').read().strip()
os.environ['GEMINI_API_KEY_2'] = open('.secrets/gemini_api_key_2.txt').read().strip()
os.environ['GEMINI_API_KEY_3'] = open('.secrets/gemini_api_key_3.txt').read().strip()

TESTS = [
    ("CountyFusion Lexington", "counties_sc.sc_countyfusion_rod", "SCCountyFusionROD", {"county": "lexington"}),
    ("NC eCourts Estates", "counties_nc.nc_ecourts_estates", "NCECourtsEstates", {}),
    ("Lexington Probate", "counties_sc.lexington_probate", "LexingtonProbateScraper", {}),
    ("SC SOS", "national.sc_sos_entity", "SCSOSBusinessSearch", {}),
    ("Orangeburg ROD", "counties_sc.orangeburg_scrod", "OrangeburgSCROD", {}),
    ("CCS Deeds", "counties_nc.nc_cchs_deeds", "NcCchsDeedsScraper", {}),
    ("Darlington", "counties_sc.darlington_recordhub", "DarlingtonRecordhub", {}),
    ("Avenu Williamsburg", "counties_sc.sc_avenu_rod", "SCAvenuROD", {"county": "williamsburg"}),
]

async def test_one(name, module, cls, kwargs):
    """Test one scraper"""
    print(f"\n{'='*70}")
    print(f"Testing: {name}")
    print(f"{'='*70}")
    
    try:
        mod = __import__(f"foreclosure_scraper.scrapers.{module}", fromlist=[cls])
        ScraperClass = getattr(mod, cls)
        scraper = ScraperClass(**kwargs)
        
        result = await asyncio.wait_for(scraper.fetch(), timeout=120)
        listings = list(result) if result else []
        
        if listings:
            print(f"✅ SUCCESS: {len(listings)} listings")
            first = listings[0].model_dump()
            print(f"   First listing:")
            print(f"     Type: {first.get('listing_type', 'N/A')}")
            print(f"     County: {first.get('county', 'N/A')}")
            return (name, True, len(listings))
        else:
            print(f"⚠️  Returned 0 listings")
            return (name, False, 0)
            
    except asyncio.TimeoutError:
        print(f"❌ TIMEOUT")
        return (name, False, 0)
    except Exception as e:
        print(f"❌ ERROR: {str(e)[:80]}")
        import traceback
        traceback.print_exc()
        return (name, False, 0)

async def main():
    print("🧪 VERIFYING TOP 10 SCRAPERS\n")
    
    results = []
    for test in TESTS:
        result = await test_one(*test)
        results.append(result)
        await asyncio.sleep(2)
    
    # Summary
    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}\n")
    
    working = [(n, c) for n, s, c in results if s and c > 0]
    empty = [n for n, s, c in results if s and c == 0]
    broken = [n for n, s, c in results if not s]
    
    print(f"✅ WORKING ({len(working)}):")
    for name, count in working:
        print(f"   {name}: {count} listings")
    
    if empty:
        print(f"\n⚠️  EMPTY ({len(empty)}):")
        for name in empty:
            print(f"   {name}")
    
    if broken:
        print(f"\n❌ BROKEN ({len(broken)}):")
        for name in broken:
            print(f"   {name}")
    
    print(f"\n📊 Total: {len(working)}/{len(results)} working")

if __name__ == "__main__":
    asyncio.run(main())
