#!/usr/bin/env python3
"""Test Darlington RecordHub scraper"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from foreclosure_scraper.scrapers.counties_sc.darlington_recordhub import DarlingtonRecordhub

async def test():
    print("🔍 Testing Darlington RecordHub...")
    
    scraper = DarlingtonRecordhub()
    
    try:
        listings_iter = await scraper.fetch()
        listings = list(listings_iter) if listings_iter else []
        
        print(f"\n✅ SUCCESS! Got {len(listings)} listings")
        
        if listings:
            print(f"\n📊 First 3 listings:")
            for i, listing in enumerate(listings[:3]):
                print(f"\n   [{i+1}] {listing.listing_type.value}")
                data = listing.model_dump()
                print(f"       County: {data.get('county', 'N/A')}")
                print(f"       Source: {data.get('source', 'N/A')}")
                if 'recorded_date' in data:
                    print(f"       Date: {data['recorded_date']}")
                if 'grantor' in data:
                    print(f"       Parties: {data['grantor']} → {data.get('grantee', 'N/A')}")
        
        return len(listings)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 0

if __name__ == "__main__":
    count = asyncio.run(test())
    print(f"\n🏁 Total: {count} listings")
    sys.exit(0 if count > 0 else 1)
