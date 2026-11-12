#!/usr/bin/env python3
"""CountyFusion browser automation for Greenville/Greenwood (flaky search APIs)"""
import asyncio
import sys
from pathlib import Path
import re
from datetime import datetime, timedelta
sys.path.insert(0, 'src')

from patchright.async_api import async_playwright

# Credentials
secrets = Path(__file__).parent.parent / ".secrets" / "countyfusion"
username = (secrets / "username.txt").read_text().strip()
password = (secrets / "password.txt").read_text().strip()

COUNTIES = {
    "Greenville": {"host": "rod.greenvillecounty.org", "name": "GreenvilleSC"},
    "Greenwood": {"host": "www.greenwoodsc.gov", "name": "GreenwoodSC"},
}

async def test_county(county_name: str, config: dict):
    """Test one county with browser automation"""
    print(f"\n{'='*60}")
    print(f"Testing {county_name}")
    print(f"{'='*60}")
    
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    
    try:
        host = config["host"]
        name = config["name"]
        base = f"https://{host}/countyweb"
        
        print(f"1. Logging in to {host}...")
        await page.goto(f"{base}/login.jsp?countyname={name}")
        await page.wait_for_load_state("networkidle")
        
        # Fill login form (no county dropdown - it's in URL)
        await page.fill('input[name="username"]', username)
        await page.fill('input[name="password"]', password)
        
        # Find and click submit button
        submit_btns = await page.locator('input[type="submit"], button[type="submit"]').all()
        if submit_btns:
            await submit_btns[0].click()
        else:
            await page.keyboard.press("Enter")
        
        await page.wait_for_load_state("networkidle")
        print("   ✅ Login submitted")
        
        # Navigate to search
        print("2. Opening instrument search...")
        await page.goto(f"{base}/search.do")
        await page.wait_for_timeout(2000)
        
        # Fill search form with date range
        print("3. Filling search criteria...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        # Try to find date inputs
        date_inputs = await page.locator('input[type="text"]').all()
        if len(date_inputs) >= 2:
            await date_inputs[0].fill(start_date.strftime("%m/%d/%Y"))
            await date_inputs[1].fill(end_date.strftime("%m/%d/%Y"))
            print(f"   Date range: {start_date.strftime('%m/%d/%Y')} - {end_date.strftime('%m/%d/%Y')}")
        
        # Click search button
        print("4. Submitting search...")
        search_btns = await page.locator('input[value*="Search"], button:has-text("Search")').all()
        if search_btns:
            await search_btns[0].click()
            await page.wait_for_timeout(5000)  # Wait for results
        
        # Extract results from grid/table
        print("5. Extracting results...")
        
        # Try common grid selectors
        rows = await page.locator('table tr, .grid-row, .k-grid-content tr').all()
        
        listings = []
        for row in rows[:50]:  # First 50 records
            text = await row.inner_text()
            if text and len(text) > 20:  # Skip header/empty rows
                listings.append(text.strip())
        
        if listings:
            print(f"\n✅ SUCCESS! Got {len(listings)} records from {county_name}")
            print(f"\n📊 First 3 records:")
            for i, record in enumerate(listings[:3]):
                print(f"\n   [{i+1}] {record[:200]}...")
            return len(listings)
        else:
            print(f"\n❌ No records found")
            await page.screenshot(path=f"/tmp/{county_name.lower()}_search.png")
            print(f"   Screenshot: /tmp/{county_name.lower()}_search.png")
            return 0
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        await page.screenshot(path=f"/tmp/{county_name.lower()}_error.png")
        return 0
    finally:
        await browser.close()
        await playwright.stop()

async def main():
    print("🔍 Testing CountyFusion with BROWSER AUTOMATION...\n")
    
    total = 0
    for county_name, config in COUNTIES.items():
        count = await test_county(county_name, config)
        total += count
        await asyncio.sleep(2)  # Pause between counties
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {total} records extracted")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
