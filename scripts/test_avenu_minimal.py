#!/usr/bin/env python3
"""Minimal Avenu test - just login and extract whatever's already there"""
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
        
        print("2. On grid page, extracting visible data...")
        await page.wait_for_timeout(3000)
        
        # Just count rows in grid
        row_count = await page.locator('.k-grid-content tr[role="row"]').count()
        print(f"   Found {row_count} rows in grid")
        
        if row_count == 0:
            # Take screenshot to see what's there
            await page.screenshot(path="/tmp/avenu_no_data.png")
            print("   Screenshot: /tmp/avenu_no_data.png")
            
            # Check page text
            text = await page.locator('body').inner_text()
            if "no records" in text.lower():
                print("   ❌ Page says 'no records'")
            else:
                print(f"   Page text preview: {text[:200]}")
        
        return row_count
        
    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    count = asyncio.run(test())
    print(f"\n🏁 Result: {count} rows")
    sys.exit(0 if count > 0 else 1)
