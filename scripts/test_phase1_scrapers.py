#!/usr/bin/env python3
"""Test high-impact scrapers from spreadsheet that likely exist"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'src')

# Map spreadsheet platforms to known scrapers
TESTS = [
    # Already confirmed working
    ("CountyFusion Lexington", "counties_sc.sc_countyfusion_rod", "SCCountyFusionROD", {"county": "lexington"}),
    
    # Probate - high impact
    ("Tyler NC probate", "counties_nc.nc_tylertech_estates", "NcTylerTechEstatesScraper", {}),
    ("Lexington probate", "counties_sc.lexington_probate", "LexingtonProbateScraper", {}),
    ("McDowell probate", "counties_nc.mcdowell_probate", "McDowellProbate", {}),
    
    # ROD
    ("Orangeburg ROD", "counties_sc.orangeburg_scrod", "OrangeburgSCROD", {}),
    ("Cherokee ROD", "counties_sc.cherokee_scrod", "CherokeeSCROD", {}),
    
    # Tax (69 scrapers exist!)
    ("Henderson tax", "counties_nc.henderson_tax", "HendersonTaxForeclosure", {}),
    ("Mecklenburg tax", "counties_nc.mecklenburg_delinquent_tax", "MecklenburgDelinquentTax", {}),
    ("Rutherford tax", "counties_nc.rutherford_tax", "RutherfordDelinquentTax", {}),
    
    # SOS
    ("SC SOS", "national.sc_sos_entity", "SCSOSBusinessSearch", {}),
]

async def test_one(name, module_path, class_name, kwargs):
    """Test one scraper quickly"""
    try:
        mod = __import__(f"foreclosure_scraper.scrapers.{module_path}", fromlist=[class_name])
        ScraperClass = getattr(mod, class_name)
        scraper = ScraperClass(**kwargs)
        
        # Quick fetch test
        listings = await asyncio.wait_for(scraper.fetch(), timeout=60)
        lst = list(listings) if listings else []
        
        print(f"✅ {name}: {len(lst)} listings")
        return True
    except asyncio.TimeoutError:
        print(f"⏱️  {name}: timeout")
        return False
    except Exception as e:
        print(f"❌ {name}: {str(e)[:60]}")
        return False

async def main():
    print("🧪 PHASE 1 TESTING - High-impact existing scrapers\n")
    
    results = []
    for name, mod, cls, kwargs in TESTS:
        success = await test_one(name, mod, cls, kwargs)
        results.append((name, success))
        await asyncio.sleep(1)
    
    working = [n for n, s in results if s]
    broken = [n for n, s in results if not s]
    
    print(f"\n\n📊 RESULTS:")
    print(f"   ✅ Working: {len(working)}/{len(results)}")
    print(f"   ❌ Broken: {len(broken)}/{len(results)}")
    
    if working:
        print(f"\n✅ WORKING:")
        for n in working:
            print(f"   - {n}")
    
    if broken:
        print(f"\n❌ NEEDS FIXING:")
        for n in broken:
            print(f"   - {n}")

if __name__ == "__main__":
    asyncio.run(main())
