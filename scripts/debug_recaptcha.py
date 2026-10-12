#!/usr/bin/env python3
"""Debug Lincoln county tax SPA — accept disclaimer, intercept API calls."""
import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        
        # Intercept all API calls
        api_calls = []
        async def on_response(response):
            url = response.url
            ct = response.headers.get('content-type', '')
            if 'json' in ct or 'xml' in ct or 'text' in ct:
                if any(x in url.lower() for x in ['api', 'ajax', 'search', 'list', 'delinquent', 'query', 'service', 'handler', 'ashx']):
                    try:
                        body = await response.text()
                        api_calls.append({
                            'url': url[:300],
                            'status': response.status,
                            'ct': ct,
                            'body_preview': body[:1000]
                        })
                    except:
                        api_calls.append({'url': url[:300], 'status': response.status})
        
        page.on("response", on_response)
        
        url = "https://www.lincolncountytax.com/List/Delinquent"
        print(f"Navigating to {url}")
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=20000)
        
        # Accept the disclaimer
        accept_btn = page.locator("button:has-text('Accept'), input:has-text('Accept'), a:has-text('Accept')")
        if await accept_btn.count() > 0:
            print("Found Accept button, clicking...")
            await accept_btn.first.click()
            await asyncio.sleep(5)
            await page.wait_for_load_state("networkidle", timeout=15000)
        else:
            print("No Accept button found")
            # Try other selectors
            btns = await page.query_selector_all("button, a.btn, input[type='button'], input[type='submit']")
            for btn in btns:
                text = await btn.inner_text() if await btn.is_visible() else "hidden"
                print(f"  Button: {text[:100]}")
        
        # Wait for SPA to load
        await asyncio.sleep(5)
        
        # Look for tables
        tables = await page.query_selector_all("table")
        print(f"Tables found: {len(tables)}")
        for i, table in enumerate(tables):
            rows = await table.query_selector_all("tr")
            print(f"  Table {i}: {len(rows)} rows")
            if len(rows) > 0:
                first_row = await rows[0].inner_text()
                print(f"    First row: {first_row[:200]}")
                if len(rows) > 1:
                    second_row = await rows[1].inner_text()
                    print(f"    Second row: {second_row[:200]}")
        
        # Look for any data elements
        data_rows = await page.query_selector_all("[ng-repeat], .data-row, .search-result, .list-item, tr.data-row")
        print(f"Data rows found: {len(data_rows)}")
        
        # Check for any search form or filter
        inputs = await page.query_selector_all("input[type='text'], input[type='search'], select")
        print(f"Input fields: {len(inputs)}")
        for inp in inputs:
            name = await inp.get_attribute('name') or ''
            placeholder = await inp.get_attribute('placeholder') or ''
            print(f"  Input: name={name} placeholder={placeholder}")
        
        # Print API calls
        print(f"\n=== API CALLS ({len(api_calls)}) ===")
        for call in api_calls:
            print(f"  [{call.get('status', '?')}] {call['url']}")
            if 'body_preview' in call:
                print(f"    Body: {call['body_preview'][:300]}")
        
        # Get body text
        body_text = await page.inner_text("body")
        print(f"\nBody text (last 1500):\n{body_text[-1500:]}")
        
        await browser.close()

asyncio.run(main())
