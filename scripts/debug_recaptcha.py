#!/usr/bin/env python3
"""Debug Lincoln county tax SPA — intercept API calls."""
import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        
        # Intercept API calls
        api_calls = []
        async def on_response(response):
            url = response.url
            if any(x in url for x in ['api', 'Ajax', 'Search', 'List', 'Delinquent', 'query']):
                try:
                    body = await response.text()
                    api_calls.append({
                        'url': url[:200],
                        'status': response.status,
                        'body_preview': body[:500]
                    })
                except:
                    api_calls.append({'url': url[:200], 'status': response.status})
        
        page.on("response", on_response)
        
        url = "https://www.lincolncountytax.com/List/Delinquent"
        print(f"Navigating to {url}")
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=20000)
        
        # Wait a bit for SPA to load
        await asyncio.sleep(5)
        
        # Try to find and interact with any search/filter buttons
        buttons = await page.query_selector_all("button, input[type='submit'], a.btn")
        for btn in buttons:
            text = await btn.inner_text() if btn else ""
            print(f"Button: {text[:100]}")
        
        # Look for any data tables
        tables = await page.query_selector_all("table")
        print(f"Tables found: {len(tables)}")
        for i, table in enumerate(tables):
            rows = await table.query_selector_all("tr")
            print(f"  Table {i}: {len(rows)} rows")
            if rows:
                first_row = await rows[0].inner_text()
                print(f"    First row: {first_row[:200]}")
        
        # Print API calls
        print(f"\n=== API CALLS ({len(api_calls)}) ===")
        for call in api_calls:
            print(f"  [{call.get('status', '?')}] {call['url']}")
            if 'body_preview' in call:
                print(f"    Body: {call['body_preview'][:200]}")
        
        # Get body text
        body_text = await page.inner_text("body")
        print(f"\nBody text (last 1000):\n{body_text[-1000:]}")
        
        await browser.close()

asyncio.run(main())
