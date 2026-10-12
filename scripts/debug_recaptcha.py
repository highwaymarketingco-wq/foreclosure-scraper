#!/usr/bin/env python3
"""Debug Lincoln county tax SPA — trigger search to get delinquent data."""
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
            ct = response.headers.get('content-type', '')
            if 'json' in ct or 'xml' in ct or 'text' in ct:
                if 'lincolncountytax' in url or 'cloudfront' in url:
                    if any(x in url.lower() for x in ['api', 'ajax', 'search', 'list', 'delinquent', 'query', 'service', 'handler', 'ashx', 'wildfire']):
                        try:
                            body = await response.text()
                            api_calls.append({
                                'url': url[:300],
                                'status': response.status,
                                'ct': ct,
                                'body_preview': body[:2000]
                            })
                        except:
                            api_calls.append({'url': url[:300], 'status': response.status})
        
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
            await asyncio.sleep(3)
            await page.wait_for_load_state("networkidle", timeout=15000)
        
        # Wait for SPA
        await asyncio.sleep(3)
        
        # Find search input and type a wildcard
        search_input = page.locator("input[placeholder*='looking']")
        if await search_input.count() > 0:
            print("Found search input, typing 'a'...")
            await search_input.first.click()
            await asyncio.sleep(1)
            await search_input.first.fill("a")
            await asyncio.sleep(3)
            await page.wait_for_load_state("networkidle", timeout=15000)
            
            # Check if reCAPTCHA challenge appeared
            challenge = page.locator("iframe[title*='recaptcha challenge']")
            if await challenge.count() > 0:
                print("reCAPTCHA challenge appeared!")
            else:
                print("No reCAPTCHA challenge")
            
            # Check table
            tables = await page.query_selector_all("table")
            for i, table in enumerate(tables):
                rows = await table.query_selector_all("tr")
                print(f"Table {i}: {len(rows)} rows")
                for j, row in enumerate(rows[:5]):
                    cells = await row.query_selector_all("td, th")
                    cell_texts = [await c.inner_text() for c in cells]
                    print(f"  Row {j}: {cell_texts}")
        else:
            print("No search input found")
            # Try pressing Enter or clicking a search button
            search_btn = page.locator("button:has-text('Search'), a:has-text('Search')")
            if await search_btn.count() > 0:
                print("Clicking Search button...")
                await search_btn.first.click()
                await asyncio.sleep(5)
                await page.wait_for_load_state("networkidle", timeout=15000)
        
        # Print API calls
        print(f"\n=== API CALLS ({len(api_calls)}) ===")
        for call in api_calls:
            print(f"  [{call.get('status', '?')}] {call['url']}")
            if 'body_preview' in call:
                print(f"    Body: {call['body_preview'][:500]}")
        
        await browser.close()

asyncio.run(main())
