#!/usr/bin/env python3
"""
Test Polk form fill + submit with correct name= selectors.
The form is bare HTML (no JS/CSS), uses name= attributes (no IDs),
and BalanceDue option values use HTML entities (&gt;0).
"""
import asyncio
import sys
import os
import re

sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"

from foreclosure_scraper.browser_utils import start_browser

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"
POST_URL = "https://cms.revize.com/revize/apps/polkcounty/searchingtaxrecord.php"


async def test_form_submit(surname: str):
    """Test filling the form and submitting via requestSubmit."""
    print(f"\n--- Testing surname: {surname} ---", flush=True)
    browser = await start_browser(headless=False)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(8)

        content = await page.get_content()
        print(f"  Form page: {len(content)} chars", flush=True)

        # Fill form and submit
        js = """
        (async () => {
            // Radio: Both (empty value)
            const radios = document.querySelectorAll('input[name="ReportGroupDescription"]');
            for (const r of radios) { if (r.value === '') r.checked = true; }

            // Set TaxYear to 2026
            const taxYear = document.querySelector('select[name="TaxYear"]');
            if (taxYear) {
                for (let i = 0; i < taxYear.options.length; i++) {
                    if (taxYear.options[i].value === '2026') {
                        taxYear.selectedIndex = i;
                        break;
                    }
                }
            }

            // Set BalanceDue to Unpaid (>0)
            // Browser decodes &gt;0 to >0 in the .value property
            const balDue = document.querySelector('select[name="BalanceDue"]');
            if (balDue) {
                for (let i = 0; i < balDue.options.length; i++) {
                    console.log('BalanceDue option', i, 'value=' + balDue.options[i].value + ' text=' + balDue.options[i].textContent);
                    if (balDue.options[i].value === '>0') {
                        balDue.selectedIndex = i;
                        console.log('Set BalanceDue to option', i);
                        break;
                    }
                }
            }

            // Set SearchColumn to Name
            const searchCol = document.querySelector('select[name="SearchColumn"]');
            if (searchCol) {
                for (let i = 0; i < searchCol.options.length; i++) {
                    if (searchCol.options[i].value === 'Name') {
                        searchCol.selectedIndex = i;
                        break;
                    }
                }
            }

            // Set SearchText
            const txt = document.querySelector('input[name="SearchText"]');
            if (txt) txt.value = '""" + surname + """';

            // Submit
            const form = document.querySelector('form');
            if (form && form.requestSubmit) {
                form.requestSubmit();
                return 'submitted';
            }
            return 'no form or no requestSubmit';
        })()
        """
        result = await page.evaluate(js, await_promise=True)
        print(f"  Submit result: {result}", flush=True)

        # Poll for results — only taxdetail/gvhdr are real result markers
        for i in range(30):
            await asyncio.sleep(2)
            content = await page.get_content()
            low = content.lower()
            if "taxdetail" in low or "gvhdr" in low:
                print(f"  Results loaded after {(i+1)*2}s: {len(content)} chars", flush=True)
                rows = re.findall(r'taxdetail\.php\?id=(\d+)', content)
                print(f"  Found {len(rows)} row IDs", flush=True)
                if rows:
                    print(f"  First 3 IDs: {rows[:3]}", flush=True)
                return len(rows)
            if "too many records" in low:
                print(f"  Too many records (after {(i+1)*2}s)", flush=True)
                return 0
            if "no records" in low:
                print(f"  No records found (after {(i+1)*2}s)", flush=True)
                return 0

        print(f"  No results marker after 60s, page is {len(content)} chars", flush=True)
        # Print what we see
        clean = re.sub(r"<[^>]+>", " ", content)
        clean = re.sub(r"\s+", " ", clean).strip()
        print(f"  Content preview: {clean[:300]}", flush=True)
        return 0
    finally:
        try:
            browser.stop()
        except BaseException:
            pass


async def test_browser_post(surname: str):
    """Alternative: POST directly from browser context (like Avalon approach).
    The browser has the Cloudflare cookies; a fetch() POST should carry them."""
    print(f"\n--- Testing browser POST: {surname} ---", flush=True)
    browser = await start_browser(headless=False)
    try:
        # Load form page first to establish session
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(8)

        # POST via fetch from browser context
        js = """
        (async () => {
            const formData = new FormData();
            formData.append('ReportGroupDescription', '');
            formData.append('TaxYear', '2026');
            formData.append('BalanceDue', '>0');
            formData.append('SearchColumn', 'Name');
            formData.append('SearchText', '""" + surname + """');

            const resp = await fetch('""" + POST_URL + """', {
                method: 'POST',
                body: formData,
                credentials: 'include'
            });
            return await resp.text();
        })()
        """
        result = await page.evaluate(js, await_promise=True)
        print(f"  POST response: {len(result)} chars", flush=True)
        low = result.lower()
        if "taxdetail" in low or "gvhdr" in low:
            rows = re.findall(r'taxdetail\.php\?id=(\d+)', result)
            print(f"  Found {len(rows)} row IDs", flush=True)
            if rows:
                print(f"  First 3 IDs: {rows[:3]}", flush=True)
        elif "too many records" in low:
            print(f"  Too many records", flush=True)
        elif "no records" in low:
            print(f"  No records found", flush=True)
        elif "just a moment" in low or "blocked" in low:
            print(f"  CLOUDFLARE BLOCK on POST", flush=True)
        else:
            clean = re.sub(r"<[^>]+>", " ", result)
            clean = re.sub(r"\s+", " ", clean).strip()
            print(f"  Unknown: {clean[:300]}", flush=True)
        return result
    finally:
        try:
            browser.stop()
        except BaseException:
            pass


async def main():
    print("Polk Form Fill + Submit Test", flush=True)
    print("=" * 60, flush=True)

    # Test 1: form.requestSubmit() approach
    r1 = await test_form_submit("Smith")

    # Test 2: browser-context POST (fetch) approach
    r2 = await test_browser_post("Smith")

    print("\n" + "=" * 60, flush=True)
    print(f"Form submit Smith: {r1} rows", flush=True)
    print(f"Browser POST Smith: {len(r2) if r2 else 0} chars response", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
