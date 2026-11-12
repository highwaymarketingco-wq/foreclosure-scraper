#!/usr/bin/env python3
"""
Cherokee SC ROD — Production scrape via avenuinsights.com.

Login → Search DEED/MTG/SAT/LIS records → Extract + paginate → Save JSON.

Login URL: https://cherokeesc.avenuinsights.com/Public/CherokeeSC/Account/Login
Search URL: https://cherokeesc.avenuinsights.com/Public/CherokeeSC/DynamicSearch/Index/2
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta

from patchright.async_api import async_playwright

LOGIN_URL = "https://cherokeesc.avenuinsights.com/Public/CherokeeSC/Account/Login"
SEARCH_URL = "https://cherokeesc.avenuinsights.com/Public/CherokeeSC/DynamicSearch/Index/2"
EMAIL = "highwaymarketingco@gmail.com"
PASSWORD = os.environ.get("CHEROKEE_SC_PASSWORD", "")
OUTPUT_PATH = "data/walled_output/cherokee_rod.json"

if not PASSWORD:
    print("ERROR: CHEROKEE_SC_PASSWORD env var not set")
    sys.exit(1)


async def login(page):
    """Login to Cherokee SC avenuinsights."""
    print(f"Loading login page: {LOGIN_URL}")
    await page.goto(LOGIN_URL, timeout=60000)
    await asyncio.sleep(5)

    # Fill email
    email_field = await page.query_selector("#Email")
    if not email_field:
        email_field = await page.query_selector("input[name='Email']")
    if not email_field:
        # Fallback: find any text/email input
        inputs = await page.query_selector_all("input[type='text'], input[type='email'], input:not([type])")
        for inp in inputs:
            name = await inp.get_attribute("name") or ""
            iid = await inp.get_attribute("id") or ""
            if "email" in name.lower() or "email" in iid.lower():
                email_field = inp
                break
    if not email_field:
        print("ERROR: Cannot find email field")
        await page.screenshot(path="/tmp/cherokee_no_email.png")
        return False
    await email_field.fill(EMAIL)
    print(f"Email filled: {EMAIL}")

    # Fill password — use type() instead of fill() for tricky fields
    password_field = await page.query_selector("input[type='password']")
    if not password_field:
        print("ERROR: Cannot find password field")
        return False
    await password_field.click()
    await password_field.fill(PASSWORD)
    # Verify it was filled
    pw_val = await password_field.evaluate("el => el.value")
    if not pw_val:
        print("  fill() failed, trying type()...")
        await password_field.click()
        await page.keyboard.type(PASSWORD, delay=50)
        pw_val = await password_field.evaluate("el => el.value")
    if not pw_val:
        print("ERROR: Cannot fill password field")
        return False
    print(f"Password filled (len={len(pw_val)})")

    # Click login — try multiple methods
    login_btn = await page.query_selector("#LoginBtn")
    if not login_btn:
        login_btn = await page.query_selector("button[type='submit']")
    if not login_btn:
        login_btn = await page.query_selector("input[type='submit']")
    if not login_btn:
        # Fallback: find any button with "Login" or "Log In" text
        btns = await page.query_selector_all("button, input[type='submit'], a.btn")
        for btn in btns:
            tag = await btn.evaluate("el => el.tagName")
            text = await btn.inner_text() if tag != "INPUT" else await btn.get_attribute("value") or ""
            if text and "login" in text.lower():
                login_btn = btn
                break

    if login_btn:
        await login_btn.click()
    else:
        # Last resort: press Enter in password field
        await password_field.press("Enter")
    print("Login submitted, waiting...")
    await asyncio.sleep(15)

    # Check if logged in
    if "Login" in page.url:
        print(f"ERROR: Still on login page: {page.url}")
        await page.screenshot(path="/tmp/cherokee_login_fail.png")
        # Dump the error message
        error_el = await page.query_selector(".text-danger, .field-validation-error, .validation-summary-errors, [class*='error']")
        if error_el:
            error_text = await error_el.inner_text()
            print(f"  Error text: {error_text}")
        # Dump page text for debugging
        page_text = await page.evaluate("() => document.body.innerText.substring(0, 2000)")
        print(f"  Page text: {page_text[:500]}")
        return False

    print(f"Logged in! URL: {page.url}")
    await page.screenshot(path="/tmp/cherokee_logged_in.png")
    return True


async def extract_results(page):
    """Extract table rows from current page."""
    results = await page.evaluate("""() => {
        // Try multiple table selectors
        let rows = document.querySelectorAll('table tr, .k-grid-content tr, .data-grid tr, .grid-content tr');
        const records = [];
        const headers = Array.from(document.querySelectorAll('table th, .k-grid-header th, .grid-header th'))
            .map(h => h.innerText.trim());

        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length < 2) continue;
            const record = {};
            cells.forEach((cell, i) => {
                const key = headers[i] || `col_${i}`;
                record[key] = cell.innerText.trim();
                const link = cell.querySelector('a');
                if (link) record[`${key}_link`] = link.href;
            });
            if (Object.keys(record).length > 1) records.push(record);
        }
        return records;
    }""")
    return results


async def search_and_extract(page, book_type="", description=""):
    """Search for records and extract results with pagination."""
    print(f"\n--- Searching: BookType='{book_type}' Description='{description}' ---")
    await page.goto(SEARCH_URL, timeout=60000)
    await asyncio.sleep(4)

    # Fill BookType (select element)
    if book_type:
        bt = await page.query_selector("#BookType")
        if not bt:
            bt = await page.query_selector("select[name='BookType']")
        if bt:
            try:
                await bt.select_option(label=book_type)
                print(f"  Selected BookType: {book_type}")
            except Exception:
                try:
                    await bt.select_option(value=book_type)
                    print(f"  Selected BookType (by value): {book_type}")
                except Exception as e:
                    print(f"  BookType select failed: {e}")
        else:
            print(f"  BookType select not found")

    # Fill IndexDescription
    if description:
        desc = await page.query_selector("#IndexDescription")
        if not desc:
            desc = await page.query_selector("input[name='IndexDescription']")
        if desc:
            await desc.fill(description)
            print(f"  Filled IndexDescription: {description}")

    # Click search
    search_btn = await page.query_selector("#btnArchiveSearch")
    if not search_btn:
        search_btn = await page.query_selector("input[type='button'][value='Search']")
    if not search_btn:
        search_btn = await page.query_selector("button[type='submit']")

    if not search_btn:
        print("  ERROR: Cannot find search button")
        return []

    await search_btn.click()
    print("  Search clicked, waiting for results...")
    await asyncio.sleep(8)

    # Extract results
    results = await extract_results(page)
    print(f"  Page 1: {len(results)} records")

    if results:
        for i, r in enumerate(results[:3]):
            print(f"    Record {i}: {json.dumps(r, default=str)[:200]}")

    # Paginate
    all_results = list(results)
    page_num = 2
    for _ in range(50):  # max 50 pages
        # Look for next page button
        next_btn = None
        btns = await page.query_selector_all("button, input[type='button'], a")
        for btn in btns:
            try:
                tag = await btn.evaluate("el => el.tagName")
                text = await btn.inner_text() if tag != "INPUT" else await btn.get_attribute("value") or ""
                if text and text.strip() in ("Next", ">", "›", "»", "Next >"):
                    next_btn = btn
                    break
            except Exception:
                continue

        if not next_btn:
            # Try Kendo UI pager
            next_btn = await page.query_selector(".k-pager-next, a[title='Go to the next page'], .next")
        
        if not next_btn:
            print(f"  No next button — stopping at page {page_num - 1}")
            break

        try:
            await next_btn.click()
            await asyncio.sleep(5)
            page_results = await extract_results(page)
            print(f"  Page {page_num}: {len(page_results)} records")
            if not page_results:
                print("  Empty page — stopping")
                break
            all_results.extend(page_results)
            page_num += 1
        except Exception as e:
            print(f"  Pagination error: {e}")
            break

    print(f"  Total for this search: {len(all_results)} records")
    return all_results


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
            print("\nLogin failed!")
            await browser.close()
            return

        all_results = []

        # Search different document types
        searches = [
            ("DEED", ""),          # All deeds
            ("MTG", ""),           # All mortgages
            ("SAT", ""),           # All satisfactions
            ("LIS", ""),           # All lis pendens
            ("", "FORECLOSURE"),   # Search description for FORECLOSURE
            ("", "TAX"),           # Search description for TAX
            ("", "LIEN"),          # Search description for LIEN
        ]

        for book_type, desc in searches:
            try:
                results = await search_and_extract(page, book_type, desc)
                # Tag with search context
                for r in results:
                    r["_search_booktype"] = book_type
                    r["_search_desc"] = desc
                    r["_source"] = "cherokee_sc_rod"
                    r["_scraped_at"] = datetime.utcnow().isoformat() + "Z"
                all_results.extend(results)
            except Exception as e:
                print(f"  Search error: {e}")
                continue

        # Dedupe by all fields
        seen = set()
        unique = []
        for r in all_results:
            key = json.dumps(r, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                unique.append(r)

        print(f"\n{'='*60}")
        print(f"TOTAL unique records: {len(unique)}")
        print(f"From {len(searches)} searches")

        # Save
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(unique, f, indent=2, default=str)
        print(f"Saved to {OUTPUT_PATH}")

        await page.screenshot(path="/tmp/cherokee_final.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
