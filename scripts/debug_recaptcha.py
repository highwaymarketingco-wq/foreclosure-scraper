#!/usr/bin/env python3
"""Debug Lincoln county tax — query Wildfire/Records API directly."""
import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        
        # Intercept the Records API call
        records_response = None
        async def on_response(response):
            url = response.url
            if 'Wildfire/Records' in url and response.request.method == 'POST':
                nonlocal records_response
                try:
                    body = await response.text()
                    records_response = {
                        'url': url,
                        'method': response.request.method,
                        'request_body': response.request.post_data,
                        'request_headers': dict(response.request.headers),
                        'response_body': body[:5000]
                    }
                except:
                    pass
        
        page.on("response", on_response)
        
        url = "https://www.lincolncountytax.com/List/Delinquent"
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=20000)
        
        # Accept disclaimer
        accept_btn = page.locator("button:has-text('Accept')")
        if await accept_btn.count() > 0:
            await accept_btn.first.click()
            await asyncio.sleep(2)
        
        # Close tips modal
        close_btn = page.locator("button:has-text('Close')")
        if await close_btn.count() > 0:
            await close_btn.first.click()
            await asyncio.sleep(1)
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)
        
        # Type and search
        search_input = page.locator("#searchBox")
        await search_input.first.click()
        await asyncio.sleep(0.5)
        await search_input.first.fill("a")
        await asyncio.sleep(2)
        await page.keyboard.press("Enter")
        await asyncio.sleep(10)
        
        if records_response:
            print("=== RECORDS API REQUEST ===")
            print(f"URL: {records_response['url']}")
            print(f"Method: {records_response['method']}")
            print(f"Request body: {records_response.get('request_body', 'N/A')}")
            print(f"\n=== RESPONSE (first 3000 chars) ===")
            print(records_response['response_body'][:3000])
        else:
            print("No Records API call captured")
        
        # Also check if there are any filter buttons/tabs for delinquent
        btns = await page.query_selector_all("button, a.btn, .nav-link, .tab")
        for btn in btns:
            text = await btn.inner_text()
            if any(x in text.lower() for x in ['delinquent', 'unpaid', 'past due', 'owed', 'filter']):
                print(f"Filter button found: {text}")
        
        await browser.close()

asyncio.run(main())
