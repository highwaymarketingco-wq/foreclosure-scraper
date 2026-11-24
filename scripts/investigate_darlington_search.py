#!/usr/bin/env python3
"""
Test Darlington RecordHub search interface AFTER login to see the real structure.

We know:
- Login works (reCAPTCHA + POST)
- Search is placeholder with guesses
- Need to see ACTUAL search interface after auth

This script:
1. Logs in successfully
2. Navigates to search
3. Screenshots + saves HTML
4. Logs all form fields/structure
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "src")

from playwright.async_api import async_playwright
from foreclosure_scraper.scrapers.counties_sc.darlington_recordhub import (
    _login,
    _SEARCH_URL,
    _load_credentials
)

async def investigate():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Keep visible
        page = await browser.new_page()
        
        # Step 1: Login
        print("🔐 Logging in...")
        success = await _login(page)
        
        if not success:
            print("❌ Login failed")
            await browser.close()
            return
        
        print("✅ Login succeeded!")
        
        # Step 2: Navigate to search
        print(f"🔍 Navigating to {_SEARCH_URL}...")
        await page.goto(_SEARCH_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # Step 3: Save screenshot
        await page.screenshot(path="darlington_search_interface.png")
        print("📸 Screenshot saved: darlington_search_interface.png")
        
        # Step 4: Save HTML
        html = await page.content()
        Path("darlington_search_interface.html").write_text(html)
        print("💾 HTML saved: darlington_search_interface.html")
        
        # Step 5: Extract all form fields
        forms = await page.query_selector_all("form")
        print(f"\n📋 Found {len(forms)} form(s)")
        
        for i, form in enumerate(forms, 1):
            print(f"\n  Form {i}:")
            form_id = await form.get_attribute("id")
            form_action = await form.get_attribute("action")
            print(f"    ID: {form_id}")
            print(f"    Action: {form_action}")
            
            inputs = await form.query_selector_all("input, select, textarea")
            print(f"    Fields ({len(inputs)}):")
            
            for inp in inputs:
                name = await inp.get_attribute("name")
                inp_type = await inp.get_attribute("type")
                inp_id = await inp.get_attribute("id")
                placeholder = await inp.get_attribute("placeholder")
                print(f"      - {name or inp_id}: type={inp_type}, placeholder={placeholder}")
        
        # Step 6: Check for DataTables/grids
        has_datatable = await page.evaluate("""() => {
            return typeof jQuery !== 'undefined' && jQuery.fn.DataTable !== undefined;
        }""")
        print(f"\n🎲 DataTables available: {has_datatable}")
        
        if has_datatable:
            tables = await page.evaluate("""() => {
                return jQuery('table').map((i, t) => ({
                    id: t.id,
                    classes: t.className,
                    rows: jQuery(t).find('tr').length
                })).get();
            }""")
            print(f"   Tables: {tables}")
        
        # Step 7: Check for Kendo grids
        has_kendo = await page.evaluate("""() => {
            return typeof kendo !== 'undefined';
        }""")
        print(f"🌐 Kendo UI available: {has_kendo}")
        
        # Keep browser open for manual inspection
        print("\n✋ Browser staying open - inspect the interface manually")
        print("   Press Ctrl+C when done")
        
        try:
            await asyncio.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            print("\n👋 Closing...")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(investigate())
