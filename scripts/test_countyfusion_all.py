#!/usr/bin/env python3
"""Test CountyFusion with correct domains (user verified)"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from foreclosure_scraper.scrapers.counties_sc.sc_countyfusion_rod import SCCountyFusionROD

async def test():
    print("🔍 Testing CountyFusion with USER-VERIFIED domains...\n")
    
    scraper = SCCountyFusionROD()
    
    # Test each county with its correct domain
    counties = ["Lexington", "Orangeburg", "Greenville", "Greenwood"]
    
    for county in counties:
        print(f"\n{'='*60}")
        print(f"Testing {county}...")
        print(f"{'='*60}")
        
        try:
            # fetch() returns Iterable[Listing], not AsyncIterable
            all_listings = await scraper.fetch()
            listings = [l for l in all_listings if l.county.lower() == county.lower()][:20]
            
            print(f"\n✅ {county}: Got {len(listings)} listings")
            
            if listings:
                print(f"\n📊 First 2 records:")
                for i, listing in enumerate(listings[:2]):
                    data = listing.model_dump()
                    print(f"\n   [{i+1}] {data['listing_type']}")
                    print(f"       County: {data['county']}")
                    print(f"       Book/Page: {data.get('book', 'N/A')}/{data.get('page', 'N/A')}")
                    if 'grantor' in data:
                        print(f"       {data['grantor']} → {data.get('grantee', 'N/A')}")
        
        except Exception as e:
            print(f"\n❌ {county} FAILED: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print("TEST COMPLETE")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(test())
