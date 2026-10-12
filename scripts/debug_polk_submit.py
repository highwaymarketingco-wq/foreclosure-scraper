"""Debug: Try multiple submit approaches for Polk search form."""
import asyncio
from foreclosure_scraper.browser_utils import start_browser

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"

async def test():
    browser = await start_browser(headless=False)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(12)
        html = await page.get_content()
        print(f"Initial page: {len(html)} chars")
        print(f"Has SearchText: {'SearchText' in html}")

        # Approach 1: Fill form via JS, then use nodriver's native click
        fill_js = """
        (async () => {
            const radios = document.querySelectorAll('input[name="ReportGroupDescription"]');
            for (const r of radios) { if (r.value === '') r.checked = true; }

            const setSelect = (name, val) => {
                const sel = document.querySelector(`select[name="${name}"]`);
                if (sel) { sel.value = val; sel.dispatchEvent(new Event('change', {bubbles: true})); }
            };
            setSelect('TaxYear', '2026');
            setSelect('BalanceDue', '>0');
            setSelect('SearchColumn', 'Name');

            const txt = document.querySelector('input[name="SearchText"]');
            if (txt) { txt.value = 'b'; txt.dispatchEvent(new Event('input', {bubbles: true})); }
            return 'filled';
        })()
        """
        result = await page.evaluate(fill_js, await_promise=True)
        print(f"Form fill result: {result}")

        # Try nodriver's find + click on submit button
        try:
            submit = await page.find("input[type='submit']", best_match=True)
            if submit:
                await submit.click()
                print("Clicked submit via nodriver find")
            else:
                print("No submit button found via find")
        except Exception as e:
            print(f"nodriver find/click error: {e}")

        # Wait for results
        for i in range(15):
            await asyncio.sleep(2)
            content = await page.get_content()
            if len(content) > 5000 or "taxdetail" in content.lower():
                print(f"Results loaded after {i*2+2}s: {len(content)} chars")
                break
        else:
            print(f"No results after 30s: {len(content)} chars")

        final = await page.get_content()
        print(f"Final page: {len(final)} chars")
        print(f"Has taxdetail: {'taxdetail' in final.lower()}")
        print(f"Has oddRow: {'oddRow' in final}")
        print(f"Has evenRow: {'evenRow' in final}")

        # Save
        with open("/tmp/polk_submit_test.html", "w") as f:
            f.write(final)
        print("Saved to /tmp/polk_submit_test.html")

        # Print snippet of any table rows
        import re
        trs = re.findall(r'<tr[^>]*>.*?</tr>', final, re.S)
        print(f"TR elements: {len(trs)}")
        for i, tr in enumerate(trs[:3]):
            clean = re.sub(r'<[^>]+>', ' ', tr).strip()
            if clean:
                print(f"  Row {i} text: {clean[:200]}")

    finally:
        try:
            browser.stop()
        except BaseException:
            pass

asyncio.run(test())
