"""Cherokee SC — avenuinsights property records search.

Login: https://cherokeesc.avenuinsights.com/Public/CherokeeSC/Account/Login
After login: https://cherokeesc.avenuinsights.com/Public/CherokeeSC/DynamicSearch/Index/2

Form fields on search page:
  BookType, Series, IndexDescription, Volume, PageNumber, PageNumberSuffix
  Search button: id=btnArchiveSearch

Goal: Search for deeds/records, extract listing data.
"""
import asyncio
import os
import sys
import time
from typing import Any

import httpx
from patchright.async_api import async_playwright

LOGIN_URL = "https://cherokeesc.avenuinsights.com/Public/CherokeeSC/Account/Login"
SEARCH_URL = "https://cherokeesc.avenuinsights.com/Public/CherokeeSC/DynamicSearch/Index/2"
EMAIL = "highwaymarketingco@gmail.com"
PASSWORD = os.environ.get("CHEROKEE_SC_PASSWORD", "")

if not PASSWORD:
    print("ERROR: CHEROKEE_SC_PASSWORD env var not set")
    sys.exit(1)


async def login(page):
    """Login to Cherokee SC."""
    print(f"Loading login page: {LOGIN_URL}")
    await page.goto(LOGIN_URL, timeout=60000)
    await asyncio.sleep(3)

    # Fill email
    email_field = await page.query_selector("#Email")
    if not email_field:
        email_field = await page.query_selector("input[name='Email']")
    if not email_field:
        print("ERROR: Cannot find email field")
        return False
    await email_field.fill(EMAIL)

    # Fill password
    password_field = await page.query_selector("input[type='password']")
    if not password_field:
        print("ERROR: Cannot find password field")
        return False
    await password_field.fill(PASSWORD)

    # Click login
    login_btn = await page.query_selector("#LoginBtn")
    if not login_btn:
        login_btn = await page.query_selector("button[type='submit']")
    if not login_btn:
        print("ERROR: Cannot find login button")
        return False
    await login_btn.click()
    print("Login clicked, waiting...")
    await asyncio.sleep(8)

    # Check if logged in
    if "Login" in page.url:
        print(f"ERROR: Still on login page: {page.url}")
        return False
    print(f"Logged in! URL: {page.url}")
    return True


async def search_and_extract(page, book_type="", description=""):
    """Search for records and extract results."""
    print(f"\nSearching: BookType='{book_type}' Description='{description}'")
    await page.goto(SEARCH_URL, timeout=60000)
    await asyncio.sleep(3)

    # Fill BookType
    if book_type:
        bt = await page.query_selector("#BookType")
        if bt:
            await bt.fill(book_type)
            print(f"Filled BookType: {book_type}")

    # Fill IndexDescription
    if description:
        desc = await page.query_selector("#IndexDescription")
        if desc:
            await desc.fill(description)
            print(f"Filled IndexDescription: {description}")

    # Click search
    search_btn = await page.query_selector("#btnArchiveSearch")
    if not search_btn:
        search_btn = await page.query_selector("input[type='button'][value='Search']")
    if not search_btn:
        print("ERROR: Cannot find search button")
        return []

    await search_btn.click()
    print("Search clicked, waiting for results...")
    await asyncio.sleep(8)

    # Extract results from table
    results = await page.evaluate("""() => {
        const rows = document.querySelectorAll('table tr, .k-grid-content tr, .data-grid tr');
        const records = [];
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length >= 2) {
                const record = {};
                const headers = document.querySelectorAll('table th, .k-grid-header th');
                const headerTexts = Array.from(headers).map(h => h.innerText.trim());
                cells.forEach((cell, i) => {
                    const key = headerTexts[i] || `col_${i}`;
                    record[key] = cell.innerText.trim();
                    // Also grab links
                    const link = cell.querySelector('a');
                    if (link) record[`${key}_link`] = link.href;
                });
                if (Object.keys(record).length > 1) records.push(record);
            }
        }
        return records;
    }""")

    print(f"Found {len(results)} records")
    for i, r in enumerate(results[:5]):
        print(f"  Record {i}: {r}")

    return results


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        # Login
        if not await login(page):
            await browser.close()
            return

        all_results = []

        # Try different search combinations
        # BookType options: DEED, MTG, SAT, LIS, etc.
        searches = [
            ("DEED", ""),          # All deeds
            ("MTG", ""),           # All mortgages
            ("SAT", ""),           # All satisfactions
            ("LIS", ""),           # All lis pendens
            ("", "FORECLOSURE"),   # Search description for FORECLOSURE
            ("", "TAX"),           # Search description for TAX
        ]

        for book_type, desc in searches:
            results = await search_and_extract(page, book_type, desc)
            all_results.extend(results)

            # Check for pagination
            page_btns = await page.query_selector_all("button[type='submit']")
            page_texts = []
            for btn in page_btns:
                t = await btn.inner_text()
                page_texts.append(t.strip())
            print(f"  Pagination buttons: {page_texts}")

            # Click through pages if available
            for _ in range(20):  # max 20 pages
                next_btn = None
                for btn in page_btns:
                    t = await btn.inner_text()
                    if t.strip() == "Next" or ">" in t:
                        next_btn = btn
                        break
                if not next_btn:
                    break
                await next_btn.click()
                await asyncio.sleep(5)
                page_results = await page.evaluate("""() => {
                    const rows = document.querySelectorAll('table tr, .k-grid-content tr, .data-grid tr');
                    const records = [];
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 2) {
                            const record = {};
                        const headers = document.querySelectorAll('table th, .k-grid-header th');
                        const headerTexts = Array.from(headers).map(h => h.innerText.trim());
                            cells.forEach((cell, i) => {
                                const key = headerTexts[i] || `col_${i}`;
                                record[key] = cell.innerText.trim();
                                const link = cell.querySelector('a');
                                if (link) record[`${key}_link`] = link.href;
                            });
                            if (Object.keys(record).length > 1) records.push(record);
                        }
                    }
                    return records;
                }""")
                print(f"  Page: {len(page_results)} records")
                all_results.extend(page_results)
                page_btns = await page.query_selector_all("button[type='submit']")

        print(f"\n=== TOTAL: {len(all_results)} records ===")

        # Save results
        import json
        with open("/tmp/cherokee_results.json", "w") as f:
            json.dump(all_results, f, indent=2)
        print("Results saved to /tmp/cherokee_results.json")

        await browser.close()


asyncio.run(main())
