#!/usr/bin/env python3
"""Avenu Insights - Complete browser workflow"""
import asyncio
import sys
from pathlib import Path
import json
sys.path.insert(0, 'src')

from patchright.async_api import async_playwright
from datetime import datetime, timedelta

secrets = Path(__file__).parent.parent / ".secrets" / "avenu_insights"
email = (secrets / "email.txt").read_text().strip()
password = (secrets / "password.txt").read_text().strip()

async def test_avenu(county: str):
    """Test Avenu with complete workflow"""
    print(f"\n{'='*60}")
    print(f"Testing {county.title()}")
    print(f"{'='*60}")
    
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)  # Visible to debug
    page = await browser.new_page()
    
    try:
        url = f"https://{county}sc.avenuinsights.com"
        
        print(f"1. Logging in to {url}...")
        await page.goto(f"{url}/Public/{county}sc/Account/Login")
        await page.fill('input[name="Email"]', email)
        await page.fill('input[name="Password"]', password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        print("   ✅ Login successful")
        
        print("2. Navigating to grid...")
        await page.goto(f"{url}/Public/{county}sc/InstrumentGrid")
        await page.wait_for_timeout(3000)
        
        print("3. Looking for search controls...")
        
        # The grid might have a "Search Criteria" section - expand it
        try:
            expand_btns = await page.locator('button, a, span').all()
            for btn in expand_btns:
                text = await btn.inner_text() if await btn.is_visible() else ""
                if "search" in text.lower() or "criteria" in text.lower():
                    try:
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        print(f"   Clicked: {text}")
                    except:
                        pass
        except:
            pass
        
        # Try submitting default search (often works without customization)
        print("4. Trying default search...")
        
        # Look for submit/search buttons
        buttons = await page.locator('button, input[type="submit"], input[type="button"]').all()
        for btn in buttons[:10]:  # First 10 buttons
            try:
                if not await btn.is_visible():
                    continue
                text = (await btn.inner_text() if await btn.is_visible() else "") or ""
                value = await btn.get_attribute("value") or ""
                
                if "search" in (text + value).lower() and "clear" not in (text + value).lower():
                    print(f"   Found search button: {text or value}")
                    await btn.click()
                    await page.wait_for_timeout(5000)
                    break
            except:
                continue
        
        # Wait for grid to populate
        print("5. Waiting for grid data...")
        await page.wait_for_timeout(3000)
        
        # Extract from grid
        print("6. Extracting data...")
        
        # Try multiple grid selectors
        listings = await page.evaluate("""() => {
            const results = [];
            
            // Try Kendo Grid
            const gridRows = document.querySelectorAll('.k-grid-content tr[role="row"], table tbody tr, .grid-row');
            
            gridRows.forEach(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 3) {
                    const text = Array.from(cells).map(c => c.textContent?.trim() || '').join(' | ');
                    if (text.length > 10) {
                        results.push(text);
                    }
                }
            });
            
            return results;
        }""")
        
        if listings and len(listings) > 0:
            print(f"\n✅ SUCCESS! Got {len(listings)} records")
            print(f"\n📊 First 3 records:")
            for i, record in enumerate(listings[:3]):
                print(f"\n   [{i+1}] {record[:150]}...")
            return len(listings)
        else:
            print("\n❌ No records found")
            await page.screenshot(path=f"/tmp/avenu_{county}_grid.png")
            print(f"   Screenshot: /tmp/avenu_{county}_grid.png")
            
            # Debug: show page text
            body_text = await page.inner_text('body')
            print(f"   Page preview: {body_text[:300]}...")
            return 0
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        await page.screenshot(path=f"/tmp/avenu_{county}_error.png")
        return 0
    finally:
        await browser.close()
        await playwright.stop()

async def main():
    print("🔍 Testing Avenu Insights with BROWSER...\n")
    
    counties = ["williamsburg", "kershaw", "newberry"]
    total = 0
    
    for county in counties:
        count = await test_avenu(county)
        total += count
        await asyncio.sleep(2)
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {total} records")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
