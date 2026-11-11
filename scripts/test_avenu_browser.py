#!/usr/bin/env python3
"""Avenu Insights with browser automation to extract grid data"""
import asyncio
import sys
import json
from pathlib import Path
sys.path.insert(0, 'src')

from patchright.async_api import async_playwright

async def test():
    print("🔍 Testing Avenu with browser automation...")
    
    # Load credentials
    secrets = Path(__file__).parent.parent / ".secrets" / "avenu_insights"
    email = (secrets / "email.txt").read_text().strip()
    password = (secrets / "password.txt").read_text().strip()
    
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    
    try:
        county = "williamsburg"
        url = f"https://{county}sc.avenuinsights.com"
        
        print(f"\n1. Navigating to {url}...")
        await page.goto(f"{url}/Public/{county}sc/Account/Login")
        await page.wait_for_load_state("networkidle")
        
        print("2. Logging in...")
        await page.fill('input[name="Email"]', email)
        await page.fill('input[name="Password"]', password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        
        if "InstrumentGrid" not in page.url:
            print(f"❌ Login failed - landed on {page.url}")
            return 0
        
        print("✅ Login successful!")
        
        print("\n3. Submitting search...")
        # Click search form, fill dates, submit
        await page.wait_for_selector('input[name="FromDate"]', timeout=10000)
        await page.fill('input[name="FromDate"]', "01/01/2024")
        await page.fill('input[name="ToDate"]', "12/31/2024")
        
        # Select distress document types
        await page.click('button:has-text("Search")')
        await page.wait_for_timeout(2000)
        
        print("\n4. Waiting for grid to load...")
        await page.wait_for_selector('.k-grid-content', timeout=10000)
        await page.wait_for_timeout(2000)
        
        print("\n5. Extracting grid data...")
        # Extract from DOM
        listings = await page.evaluate("""() => {
            const rows = document.querySelectorAll('.k-grid-content tr[role="row"]');
            const results = [];
            
            rows.forEach(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 5) {
                    results.push({
                        instrument_num: cells[0]?.textContent?.trim(),
                        doc_type: cells[1]?.textContent?.trim(),
                        recorded_date: cells[2]?.textContent?.trim(),
                        grantor: cells[3]?.textContent?.trim(),
                        grantee: cells[4]?.textContent?.trim(),
                    });
                }
            });
            
            return results;
        }""")
        
        print(f"\n✅ SUCCESS! Extracted {len(listings)} records from grid")
        
        if listings:
            print(f"\n📊 First 3 records:")
            for i, record in enumerate(listings[:3]):
                print(f"\n   [{i+1}] {record['doc_type']}")
                print(f"       Instrument: {record['instrument_num']}")
                print(f"       Date: {record['recorded_date']}")
                print(f"       Parties: {record['grantor']} → {record['grantee']}")
        
        return len(listings)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    count = asyncio.run(test())
    print(f"\n🏁 Total: {count} listings")
    sys.exit(0 if count > 0 else 1)
