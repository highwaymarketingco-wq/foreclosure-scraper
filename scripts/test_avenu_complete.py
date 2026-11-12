#!/usr/bin/env python3
"""Avenu Insights - Complete browser automation"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from patchright.async_api import async_playwright

async def test():
    secrets = Path(__file__).parent.parent / ".secrets" / "avenu_insights"
    email = (secrets / "email.txt").read_text().strip()
    password = (secrets / "password.txt").read_text().strip()
    
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    
    try:
        county = "williamsburg"
        url = f"https://{county}sc.avenuinsights.com"
        
        print(f"1. Logging in to {url}...")
        await page.goto(f"{url}/Public/{county}sc/Account/Login")
        await page.fill('input[name="Email"]', email)
        await page.fill('input[name="Password"]', password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        
        print("2. Configuring search...")
        # Wait for page to load
        await page.wait_for_timeout(2000)
        
        # Remove exclusions by clicking X on each document type filter
        # The pills like "DEED ⊗" exclude those types - we need to clear them
        exclude_buttons = page.locator('button.k-button.k-button-icon')
        count = await exclude_buttons.count()
        print(f"   Removing {count} exclusion filters...")
        
        # Click all X buttons to remove exclusions
        for i in range(count):
            try:
                await exclude_buttons.first.click(timeout=1000)
                await page.wait_for_timeout(200)
            except:
                break
        
        print("3. Submitting broad search...")
        # Now submit search with all document types included
        # The search might auto-execute when filters change, or we need to trigger it
        await page.wait_for_timeout(2000)
        
        # Check if grid has data now
        await page.wait_for_selector('.k-grid-content', timeout=10000)
        row_count = await page.locator('.k-grid-content tr[role="row"]').count()
        
        if row_count == 0:
            print("   No data yet, trying to trigger search...")
            # Try clicking in search criteria area to trigger
            await page.locator('select[id*="SearchCriteria"], select.form-control').first.click()
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)
            row_count = await page.locator('.k-grid-content tr[role="row"]').count()
        
        print(f"\n4. Extracting grid data... ({row_count} rows visible)")
        
        if row_count == 0:
            await page.screenshot(path="/tmp/avenu_debug.png")
            print("   ❌ Still no rows - screenshot saved")
            return 0
        
        # Extract data from grid
        listings = await page.evaluate("""() => {
            const rows = document.querySelectorAll('.k-grid-content tr[role="row"]');
            const results = [];
            
            rows.forEach(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 5) {
                    results.push({
                        instrument_num: cells[0]?.textContent?.trim() || '',
                        doc_type: cells[1]?.textContent?.trim() || '',
                        recorded_date: cells[2]?.textContent?.trim() || '',
                        grantor: cells[3]?.textContent?.trim() || '',
                        grantee: cells[4]?.textContent?.trim() || '',
                    });
                }
            });
            
            return results;
        }""")
        
        print(f"\n✅ SUCCESS! Extracted {len(listings)} records")
        
        if listings:
            print(f"\n📊 First 3 records:")
            for i, record in enumerate(listings[:3]):
                print(f"\n   [{i+1}] {record['doc_type']}")
                print(f"       Instrument: {record['instrument_num']}")
                print(f"       Date: {record['recorded_date']}")
                print(f"       {record['grantor']} → {record['grantee']}")
        
        return len(listings)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        await page.screenshot(path="/tmp/avenu_error.png")
        return 0
    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    count = asyncio.run(test())
    print(f"\n🏁 Total: {count} listings")
    sys.exit(0 if count > 0 else 1)
