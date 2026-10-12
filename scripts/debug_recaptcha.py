#!/usr/bin/env python3
"""Debug Lincoln county tax SPA — try search with reCAPTCHA, find search API."""
import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        
        # Intercept ALL API calls to cloudfront
        api_calls = []
        async def on_response(response):
            url = response.url
            ct = response.headers.get('content-type', '')
            if 'cloudfront' in url and ('json' in ct or 'text' in ct):
                try:
                    body = await response.text()
                    api_calls.append({
                        'url': url[:500],
                        'status': response.status,
                        'body_preview': body[:3000]
                    })
                except:
                    api_calls.append({'url': url[:500], 'status': response.status})
        
        page.on("response", on_response)
        
        url = "https://www.lincolncountytax.com/List/Delinquent"
        print(f"Navigating to {url}")
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=20000)
        
        # Accept disclaimer
        accept_btn = page.locator("button:has-text('Accept')")
        if await accept_btn.count() > 0:
            print("Clicking Accept...")
            await accept_btn.first.click()
            await asyncio.sleep(2)
        
        # Close tips modal
        close_btn = page.locator("button:has-text('Close')")
        if await close_btn.count() > 0:
            print("Closing tips modal...")
            await close_btn.first.click()
            await asyncio.sleep(1)
        
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)
        
        # Type in search box and press Enter to trigger actual search
        search_input = page.locator("#searchBox")
        if await search_input.count() > 0:
            print("Typing in search box and pressing Enter...")
            await search_input.first.click()
            await asyncio.sleep(0.5)
            await search_input.first.fill("a")
            await asyncio.sleep(2)
            
            # Press Enter to trigger search
            await page.keyboard.press("Enter")
            await asyncio.sleep(10)
            
            # Check for reCAPTCHA challenge iframe
            challenge_frame = None
            for frame in page.frames:
                if 'bframe' in frame.url:
                    challenge_frame = frame
                    print(f"Challenge frame: {frame.url[:100]}")
                    break
            
            if challenge_frame:
                print("reCAPTCHA challenge is active")
                # Try to find audio button
                try:
                    audio_btn = await challenge_frame.query_selector("#recaptcha-audio-button, .rc-button-audio")
                    if audio_btn:
                        print("Found audio button!")
                    else:
                        # Get all buttons in challenge frame
                        btns = await challenge_frame.query_selector_all("button")
                        for btn in btns:
                            title = await btn.get_attribute('title') or ''
                            aria = await btn.get_attribute('aria-label') or ''
                            print(f"  Button: title={title} aria={aria}")
                except Exception as e:
                    print(f"Error inspecting challenge: {e}")
            
            # Check table
            tables = await page.query_selector_all("table")
            for i, table in enumerate(tables):
                rows = await table.query_selector_all("tr")
                print(f"Table {i}: {len(rows)} rows")
                for j, row in enumerate(rows[:10]):
                    cells = await row.query_selector_all("td, th")
                    cell_texts = [await c.inner_text() for c in cells]
                    print(f"  Row {j}: {cell_texts}")
        
        # Print API calls
        print(f"\n=== CLOUDFRONT API CALLS ({len(api_calls)}) ===")
        for call in api_calls:
            print(f"  [{call.get('status', '?')}] {call['url']}")
            if 'body_preview' in call:
                print(f"    Body: {call['body_preview'][:500]}")
        
        await browser.close()

asyncio.run(main())
