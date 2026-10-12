#!/usr/bin/env python3
"""Quick Polk test — search 3 surnames to verify form submit + results parsing."""
import asyncio
import sys
import os
sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"

from foreclosure_scraper.browser_utils import start_browser

_SEARCH_BASE = "https://cms.revize.com/revize/apps/polkcounty"
_SEARCH_FORM_URL = f"{_SEARCH_BASE}/searchtaxrecord.php"
_CURRENT_TAX_YEAR = "2026"

TEST_TERMS = ["Smith", "Johnson", "Polk"]

async def main():
    print(f"[polk-test] Launching browser (headless=False)...")
    browser = await start_browser(headless=False)
    print(f"[polk-test] Browser launched")
    
    total_rows = 0
    for term in TEST_TERMS:
        print(f"\n[polk-test] Searching surname: {term}")
        try:
            page = await browser.get(_SEARCH_FORM_URL)
            await asyncio.sleep(10)  # Cloudflare + page render
            
            js = """
            (async () => {
                const radios = document.querySelectorAll('input[name="ReportGroupDescription"]');
                for (const r of radios) { if (r.value === '') r.checked = true; }
                
                const setSelect = (name, val) => {
                    const sel = document.querySelector(`select[name="${name}"]`);
                    if (sel) { sel.value = val; sel.dispatchEvent(new Event('change', {bubbles: true})); }
                };
                setSelect('TaxYear', '""" + _CURRENT_TAX_YEAR + """');
                setSelect('BalanceDue', '>0');
                setSelect('SearchColumn', 'Name');
                
                const txt = document.querySelector('input[name="SearchText"]');
                if (txt) { txt.value = '""" + term + """'; txt.dispatchEvent(new Event('input', {bubbles: true})); }
                
                const form = document.querySelector('form');
                if (form) {
                    if (form.requestSubmit) { form.requestSubmit(); }
                    else { form.submit(); }
                }
                return 'submitted';
            })()
            """
            result = await page.evaluate(js, await_promise=True)
            print(f"[polk-test] Form submit result: {result}")
            
            # Poll for results
            found = False
            for i in range(20):
                await asyncio.sleep(2)
                content = await page.get_content()
                clen = len(content)
                has_taxdetail = "taxdetail" in content.lower()
                has_too_many = "too many records" in content.lower()
                print(f"  poll {i+1}: {clen} chars, taxdetail={has_taxdetail}, too_many={has_too_many}")
                if has_taxdetail or (clen > 5000 and not has_too_many):
                    found = True
                    break
                if has_too_many:
                    print(f"  [polk-test] 'too many records' — surname too common")
                    break
            
            content = await page.get_content()
            clen = len(content)
            
            # Count result rows
            import re
            row_re = re.compile(r'<tr class="(?:odd|even)Row">')
            rows = row_re.findall(content)
            print(f"[polk-test] {term}: {clen} chars, {len(rows)} result rows")
            
            if len(rows) > 0:
                total_rows += len(rows)
                # Show first row sample
                name_re = re.compile(r'<tr class="(?:odd|even)Row">\s*<td>([^<]*?)</td>')
                names = name_re.findall(content)
                if names:
                    print(f"  First 3 names: {names[:3]}")
            
        except Exception as e:
            print(f"[polk-test] ERROR for {term}: {e}")
    
    try:
        browser.stop()
    except BaseException:
        pass
    
    print(f"\n[polk-test] TOTAL ROWS: {total_rows}")
    print(f"[polk-test] DONE")

asyncio.run(main())
