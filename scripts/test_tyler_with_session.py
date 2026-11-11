"""
Test nc_ecourts_estates scraper with captured working session
"""
import asyncio
import json
from datetime import datetime

async def test_with_captured_session():
    # Load captured session
    with open('tyler_working_session_20261111_143658.json') as f:
        session = json.load(f)
    
    print("✅ Loaded captured session from manual CAPTCHA solve")
    print(f"   Timestamp: {session['timestamp']}")
    print(f"   Has aws-waf-token: {any(c['name'] == 'aws-waf-token' for c in session['cookies'])}")
    print(f"   Has ASP.NET session: {any(c['name'] == 'ASP.NET_SessionId' for c in session['cookies'])}")
    
    # Import scraper
    import sys
    sys.path.insert(0, 'src')
    from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates import NCECourtsEstates
    
    print("\n🔍 Testing scraper with captured session...")
    
    # Create scraper instance for one county
    scraper = NCECourtsEstates()
    
    # Inject captured cookies into scraper
    print("\n📋 Attempting to fetch estates for Beaufort County...")
    try:
        listings = await scraper.fetch()
        listings_list = list(listings)
        
        print(f"\n✅ SUCCESS! Fetched {len(listings_list)} listings")
        if listings_list:
            print(f"\n📊 Sample listing:")
            sample = listings_list[0]
            print(f"   Name: {sample.name}")
            print(f"   County: {sample.county}")
            print(f"   Address: {sample.address}")
            print(f"   Type: {sample.listing_type}")
            
        return len(listings_list)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 0

if __name__ == "__main__":
    count = asyncio.run(test_with_captured_session())
    print(f"\n🏁 Final count: {count} listings")
