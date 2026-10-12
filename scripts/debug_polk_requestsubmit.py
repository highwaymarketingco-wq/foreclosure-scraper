"""Debug: Try form.requestSubmit() and other approaches for Polk."""
import asyncio
from foreclosure_scraper.browser_utils import start_browser

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"

async def test():
    browser = await start_browser(headless=False)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(12)
        html = await page.get_content()
        print(f"Search page: {len(html)} chars, has form: {'<form' in html}")

        # Fill form correctly — BalanceDue value is '>0' (literal, not entity)
        fill_js = """
        (async () => {
            // Set radio to "Both"
            const radios = document.querySelectorAll('input[name="ReportGroupDescription"]');
            for (const r of radios) { if (r.value === '') r.checked = true; }

            // Set selects
            const taxYearSel = document.querySelector('select[name="TaxYear"]');
            if (taxYearSel) taxYearSel.value = '2026';

            const balSel = document.querySelector('select[name="BalanceDue"]');
            // The option values are entities decoded by browser: '>0' and '<=0'
            if (balSel) balSel.value = '>0';

            const searchColSel = document.querySelector('select[name="SearchColumn"]');
            if (searchColSel) searchColSel.value = 'Name';

            // Set text
            const txt = document.querySelector('input[name="SearchText"]');
            if (txt) txt.value = 'b';

            // Verify values
            return JSON.stringify({
                radio: document.querySelector('input[name="ReportGroupDescription"]:checked')?.value,
                taxYear: taxYearSel?.value,
                balance: balSel?.value,
                searchCol: searchColSel?.value,
                searchText: txt?.value,
            });
        })()
        """
        result = await page.evaluate(fill_js, await_promise=True)
        print(f"Form values: {result}")

        # Try form.requestSubmit() — triggers submit event + validators
        submit_js = """
        (async () => {
            const form = document.querySelector('form');
            if (form.requestSubmit) {
                form.requestSubmit();
                return 'requestSubmit';
            } else {
                form.submit();
                return 'submit';
            }
        })()
        """
        result2 = await page.evaluate(submit_js, await_promise=True)
        print(f"Submit method: {result2}")

        # Wait for navigation
        for i in range(20):
            await asyncio.sleep(2)
            content = await page.get_content()
            url = await page.evaluate("window.location.href", await_promise=False)
            if len(content) > 5000 or "taxdetail" in content.lower():
                print(f"Results loaded after {i*2+2}s — URL: {url}, content: {len(content)} chars")
                break
            if i % 5 == 4:
                print(f"  Still waiting at {i*2+2}s — {len(content)} chars, URL: {url}")
        else:
            print(f"No results after 40s — {len(content)} chars")

        final = await page.get_content()
        print(f"Final: {len(final)} chars, has taxdetail: {'taxdetail' in final.lower()}, has oddRow: {'oddRow' in final}")

        with open("/tmp/polk_requestsubmit.html", "w") as f:
            f.write(final)
        print("Saved")

    finally:
        try:
            browser.stop()
        except BaseException:
            pass

asyncio.run(test())
