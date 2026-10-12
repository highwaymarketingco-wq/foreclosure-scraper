#!/usr/bin/env python3
"""Quick check: query Lincoln county Wildfire API and count delinquent vs paid."""
import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        
        url = "https://www.lincolncountytax.com/List/Delinquent"
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=20000)
        
        # Accept disclaimer
        accept = page.locator("button:has-text('Accept')")
        if await accept.count() > 0:
            await accept.first.click()
            await asyncio.sleep(2)
        
        close = page.locator("button:has-text('Close')")
        if await close.count() > 0:
            await close.first.click()
            await asyncio.sleep(1)
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)
        
        # Query API
        api_url = "https://d1ebsyxxbc7tep.cloudfront.net/data/a45b9ca6-46be-4396-9468-56194741a38e/Wildfire/Records"
        
        response = await page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({value: 'a', skip: 0, direct: false})
                });
                return await resp.text();
            }""",
            api_url,
        )
        
        data = json.loads(response)
        records = data.get("Records", [])
        total = data.get("TotalRecords", 0)
        
        delinquent = [r for r in records if r.get("isDelinquent")]
        unpaid = [r for r in records if r.get("Payment", {}).get("Status") != "Paid"]
        amount_due = [r for r in records if r.get("Values", {}).get("AmountDue", 0) > 0]
        
        print(f"Total records (API): {total}")
        print(f"Records in this page: {len(records)}")
        print(f"isDelinquent=True: {len(delinquent)}")
        print(f"Payment Status != Paid: {len(unpaid)}")
        print(f"AmountDue > 0: {len(amount_due)}")
        
        if amount_due:
            for r in amount_due[:5]:
                print(f"\n  AmountDue record:")
                print(f"    Owner: {r.get('OwnerName1')}")
                print(f"    AmountDue: {r.get('Values', {}).get('AmountDue')}")
                print(f"    Payment: {r.get('Payment', {}).get('Status')}")
                print(f"    isDelinquent: {r.get('isDelinquent')}")
                print(f"    ARStatus: {r.get('ARStatus')}")
                print(f"    CollectionStatus: {r.get('CollectionStatus')}")
        
        if unpaid:
            for r in unpaid[:5]:
                print(f"\n  Unpaid record:")
                print(f"    Owner: {r.get('OwnerName1')}")
                print(f"    AmountDue: {r.get('Values', {}).get('AmountDue')}")
                print(f"    Payment: {r.get('Payment', {}).get('Status')}")
                print(f"    isDelinquent: {r.get('isDelinquent')}")
        
        # Check if there's a RequiresGetDelinquents field
        delinq_flag = [r for r in records if r.get("RequiresGetDelinquents")]
        print(f"\nRequiresGetDelinquents=True: {len(delinq_flag)}")
        
        await browser.close()

asyncio.run(main())
