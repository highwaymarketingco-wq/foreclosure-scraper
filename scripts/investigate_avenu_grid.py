#!/usr/bin/env python3
"""Investigate Avenu Insights Kendo Grid issue.

Claude says: Kendo Grid never populates (confirmed dead 2026-11-12).
Current approach: HTTP client POSTs to grid endpoint.

HYPOTHESIS: Kendo Grid requires real browser session, not just HTTP requests.
Grid state might be session-dependent and require JS to initialize properly.

TEST:
1. Use patchright browser automation
2. Login via browser (not HTTP client)
3. Navigate to InstrumentGrid page
4. Wait for grid to load/populate
5. Inspect network requests and DOM
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from patchright.async_api import async_playwright
import structlog

log = structlog.get_logger()

COUNTY = "williamsburg"  # Smallest county
BASE_URL = f"https://{COUNTY}sc.avenuinsights.com"
LOGIN_URL = f"{BASE_URL}/Public/{COUNTY}sc/Account/Login"
GRID_URL = f"{BASE_URL}/Public/{COUNTY}sc/InstrumentGrid"


async def test_grid_via_browser():
    """Test if grid populates when accessed via real browser."""
    
    # Read credentials
    home = os.path.expanduser("~")
    with open(f"{home}/.secrets/avenu_insights/email.txt") as f:
        email = f.read().strip()
    with open(f"{home}/.secrets/avenu_insights/password.txt") as f:
        password = f.read().strip()
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # Headful for inspection
        page = await browser.new_page()
        
        # Enable request logging
        async def log_request(request):
            if "InstrumentGrid" in request.url or "Search" in request.url:
                log.info("request", method=request.method, url=request.url)
        
        async def log_response(response):
            if "InstrumentGrid" in response.url or "Search" in response.url:
                body = await response.text() if response.status == 200 else ""
                log.info("response", status=response.status, url=response.url, 
                        body_len=len(body), preview=body[:200])
        
        page.on("request", log_request)
        page.on("response", log_response)
        
        try:
            # 1. Login
            log.info("navigating_to_login", url=LOGIN_URL)
            await page.goto(LOGIN_URL, wait_until="networkidle")
            
            # Fill login form
            await page.fill("input[name='Email']", email)
            await page.fill("input[name='Password']", password)
            
            log.info("submitting_login")
            await page.click("button[type='submit'], input[type='submit']")
            
            # Wait for redirect
            await asyncio.sleep(5)
            
            current_url = page.url
            log.info("after_login", url=current_url)
            
            if "Login" in current_url:
                log.error("login_failed", url=current_url)
                await browser.close()
                return
            
            # 2. Navigate to grid page
            log.info("navigating_to_grid", url=GRID_URL)
            await page.goto(GRID_URL, wait_until="networkidle")
            await asyncio.sleep(3)
            
            # 3. Check if grid has data
            grid_rows = await page.evaluate("""() => {
                const grid = document.querySelector('.k-grid, [role="grid"], table');
                if (!grid) return null;
                
                const rows = grid.querySelectorAll('tbody tr:not(.k-no-data)');
                return rows.length;
            }""")
            
            if grid_rows and grid_rows > 0:
                log.info("✅ GRID HAS DATA", rows=grid_rows)
            else:
                # Check for "No records" message
                no_data = await page.evaluate("""() => {
                    const nodata = document.querySelector('.k-no-data, .no-records, .empty');
                    return nodata ? nodata.textContent : null;
                }""")
                
                if no_data:
                    log.warning("⚠️  GRID EMPTY", message=no_data)
                else:
                    log.warning("⚠️  GRID NOT FOUND OR NOT LOADED")
            
            # 4. Try submitting search form if visible
            search_btn = await page.query_selector("button:has-text('Search'), input[value='Search']")
            if search_btn:
                log.info("found_search_button_clicking")
                await search_btn.click()
                await asyncio.sleep(5)
                
                # Re-check grid
                grid_rows2 = await page.evaluate("""() => {
                    const rows = document.querySelectorAll('tbody tr:not(.k-no-data)');
                    return rows.length;
                }""")
                
                if grid_rows2 and grid_rows2 > 0:
                    log.info("✅ GRID POPULATED AFTER SEARCH", rows=grid_rows2)
                else:
                    log.error("❌ GRID STILL EMPTY AFTER SEARCH")
            
            # Keep browser open for manual inspection
            log.info("browser_open_press_ctrl_c")
            await asyncio.sleep(300)
            
        except KeyboardInterrupt:
            pass
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_grid_via_browser())
