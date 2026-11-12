#!/usr/bin/env python3
"""Quick Tyler test with Gemini solver - one county only"""
import asyncio
import os
import sys
sys.path.insert(0, 'src')

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates import NCECourtsEstates

async def test():
    print("🔍 Testing Tyler estates with Gemini image solver...")
    print(f"   Gemini keys loaded: {bool(os.getenv('GEMINI_API_KEY_1'))}")
    
    scraper = NCECourtsEstates()
    
    # Just test Beaufort (one county)
    print("\n📋 Fetching Beaufort County estates...")
    try:
        listings = await scraper.fetch()
        listings_list = list(listings)
        
        print(f"\n✅ SUCCESS! Got {len(listings_list)} listings")
        
        if listings_list:
            print(f"\n📊 First listing:")
            first = listings_list[0]
            print(f"   County: {first.county}")
            print(f"   Type: {first.listing_type}")
            # Print dict to see all fields
            import json
            print(json.dumps(first.model_dump(), indent=2, default=str)[:500])
        
        return len(listings_list)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        # Kill browser immediately
        import subprocess
        subprocess.run(['pkill', '-9', '-f', 'chromium'], capture_output=True)

if __name__ == "__main__":
    count = asyncio.run(test())
    print(f"\n🏁 Total: {count} listings")
    sys.exit(0 if count > 0 else 1)
