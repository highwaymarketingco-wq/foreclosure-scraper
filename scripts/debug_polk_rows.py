#!/usr/bin/env python3
"""Debug Polk row regex — dump a sample of the Johnson results HTML to see structure."""
import asyncio
import sys
import os
sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"

from foreclosure_scraper.browser_utils import start_browser

_SEARCH_FORM_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"
_CURRENT_TAX_YEAR = "2026"

async def main():
    browser = await start_browser(headless=False)
    
    for term in ["Johnson"]:
        print(f"\n[debug] Searching: {term}")
        page = await browser.get(_SEARCH_FORM_URL)
        await asyncio.sleep(10)
        
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
            if (form) { if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); } }
            return 'submitted';
        })()
        """
        await page.evaluate(js, await_promise=True)
        
        for i in range(15):
            await asyncio.sleep(2)
            content = await page.get_content()
            if len(content) > 5000 or "taxdetail" in content.lower() or "no records" in content.lower() or "too many" in content.lower():
                break
        
        content = await page.get_content()
        print(f"[debug] Content length: {len(content)}")
        
        # Save full HTML for inspection
        with open("/tmp/polk_johnson.html", "w") as f:
            f.write(content)
        print(f"[debug] Saved to /tmp/polk_johnson.html")
        
        # Print all <tr> tags with their class
        import re
        trs = re.findall(r'<tr[^>]*class="([^"]*)"[^>]*>', content)
        print(f"[debug] TR classes found: {trs[:20]}")
        
        # Print all table classes
        tables = re.findall(r'<table[^>]*class="([^"]*)"[^>]*>', content)
        print(f"[debug] Table classes: {tables}")
        
        # Check for any data rows
        all_trs = re.findall(r'<tr[^>]*>', content)
        print(f"[debug] Total <tr> tags: {len(all_trs)}")
        for t in all_trs[:10]:
            print(f"  {t}")
        
        # Check for "no records" or error messages
        for keyword in ["no records", "no results", "too many", "error", "not found", "Your search"]:
            if keyword in content.lower():
                # Find surrounding context
                idx = content.lower().find(keyword)
                snippet = content[max(0,idx-50):idx+200]
                import re as re2
                snippet = re2.sub(r'<[^>]+>', ' ', snippet)
                snippet = re2.sub(r'\s+', ' ', snippet).strip()
                print(f"[debug] Found '{keyword}': {snippet[:150]}")
    
    try:
        browser.stop()
    except BaseException:
        pass

asyncio.run(main())
