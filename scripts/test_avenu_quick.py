#!/usr/bin/env python3
"""Test Avenu Insights scraper with real credentials - one county only"""
import asyncio
import sys
sys.path.insert(0, 'src')

from foreclosure_scraper.scrapers.counties_sc.sc_avenu_rod import ScAvenuRod

async def test():
    print("🔍 Testing Avenu Insights (Williamsburg SC)...")
    
    scraper = ScAvenuRod()
    
    try:
        listings = await scraper.fetch()
        listings_list = list(listings)
        
        print(f"\n✅ SUCCESS! Got {len(listings_list)} listings from Avenu")
        
        if listings_list:
            print(f"\n📊 First 3 listings:")
            for i, item in enumerate(listings_list[:3]):
                print(f"\n   [{i+1}] County: {item.county}")
                print(f"       Type: {item.listing_type}")
                print(f"       Data: {str(item.model_dump())[:200]}...")
        
        return len(listings_list)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        import subprocess
        subprocess.run(['pkill', '-9', '-f', 'chromium'], capture_output=True)

if __name__ == "__main__":
    count = asyncio.run(test())
    print(f"\n🏁 Total Avenu listings: {count}")
    sys.exit(0 if count > 0 else 1)
