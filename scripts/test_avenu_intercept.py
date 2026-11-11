#!/usr/bin/env python3
"""Avenu Insights - Hybrid approach: browser login + intercept grid API"""
import asyncio
import sys
import json
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
    
    # Track XHR responses
    grid_data = []
    
    async def handle_response(response):
        if "InstrumentGrid" in response.url and "Read" in response.url:
            try:
                data = await response.json()
                if isinstance(data, dict) and "Data" in data:
                    grid_data.append(data["Data"])
                    print(f"   📦 Captured grid response: {len(data['Data'])} records")
            except:
                pass
    
    page.on("response", handle_response)
    
    try:
        county = "williamsburg"
        url = f"https://{county}sc.avenuinsights.com"
        
        print(f"1. Logging in to {url}...")
        await page.goto(f"{url}/Public/{county}sc/Account/Login")
        await page.fill('input[name="Email"]', email)
        await page.fill('input[name="Password"]', password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        
        print("2. Triggering grid load via navigation...")
        # Navigate directly to grid which should auto-load recent records
        await page.goto(f"{url}/Public/{county}sc/InstrumentGrid")
        await page.wait_for_timeout(5000)  # Wait for any auto-search to complete
        
        # Try clicking different areas to trigger search
        print("3. Attempting to trigger search...")
        
        # Look for any visible "Search" or "Submit" buttons
        try:
            search_btns = await page.locator('button, input[type="submit"], input[type="button"]').all()
            for btn in search_btns:
                text = await btn.inner_text() if await btn.is_visible() else ""
                if "search" in text.lower():
                    print(f"   Found search button: {text}")
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    break
        except:
            pass
        
        # Wait for any pending requests
        await page.wait_for_timeout(2000)
        
        if grid_data:
            all_records = []
            for batch in grid_data:
                all_records.extend(batch)
            
            print(f"\n✅ SUCCESS! Captured {len(all_records)} records from API")
            
            if all_records:
                print(f"\n📊 First 3 records:")
                for i, record in enumerate(all_records[:3]):
                    print(f"\n   [{i+1}] {json.dumps(record, indent=6)[:200]}...")
            
            return len(all_records)
        else:
            print("\n❌ No grid data captured")
            # Check what's on page
            await page.screenshot(path="/tmp/avenu_final.png")
            row_count = await page.locator('.k-grid-content tr[role="row"]').count()
            print(f"   DOM shows {row_count} visible rows")
            print(f"   Screenshot: /tmp/avenu_final.png")
            return 0
        
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
    print(f"\n🏁 Total: {count} records")
    sys.exit(0 if count > 0 else 1)
