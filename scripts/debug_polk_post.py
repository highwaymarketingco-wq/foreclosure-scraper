"""Debug: Try direct POST to searchingtaxrecord.php from browser context.

The form action is 'searchingtaxrecord.php' with method=POST.
Instead of filling+clicking the form (which doesn't navigate), make a
same-origin fetch POST from the browser context.
"""
import asyncio
from foreclosure_scraper.browser_utils import start_browser

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"
POST_URL = "https://cms.revize.com/revize/apps/polkcounty/searchingtaxrecord.php"

async def test():
    browser = await start_browser(headless=False)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(12)
        html = await page.get_content()
        print(f"Search page: {len(html)} chars")

        # POST directly from browser context — same-origin, Cloudflare cookies present
        post_js = """
        (async () => {
            const formData = new URLSearchParams();
            formData.append('ReportGroupDescription', '');
            formData.append('TaxYear', '2026');
            formData.append('BalanceDue', '>0');
            formData.append('SearchColumn', 'Name');
            formData.append('SearchText', 'b');

            const resp = await fetch('""" + POST_URL + """', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: formData.toString(),
                redirect: 'follow',
            });
            const text = await resp.text();
            return JSON.stringify({status: resp.status, length: text.length, snippet: text.substring(0, 1000)});
        })()
        """

        result = await page.evaluate(post_js, await_promise=True)
        print(f"POST result: {result[:500]}")

        # Parse the result
        import json
        try:
            data = json.loads(result)
            print(f"Status: {data.get('status')}, Length: {data.get('length')}")
            snippet = data.get('snippet', '')
            # Check for result indicators
            for pattern in ['oddRow', 'evenRow', 'taxdetail', 'Result', 'No results', 'no match', 'No records']:
                if pattern.lower() in snippet.lower():
                    print(f"  Found '{pattern}' in snippet")
            # Save full response
            if data.get('length', 0) > 1000:
                # Re-fetch and save full HTML
                save_js = """
                (async () => {
                    const formData = new URLSearchParams();
                    formData.append('ReportGroupDescription', '');
                    formData.append('TaxYear', '2026');
                    formData.append('BalanceDue', '>0');
                    formData.append('SearchColumn', 'Name');
                    formData.append('SearchText', 'b');
                    const resp = await fetch('""" + POST_URL + """', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: formData.toString(),
                    });
                    return await resp.text();
                })()
                """
                full = await page.evaluate(save_js, await_promise=True)
                with open("/tmp/polk_post_results.html", "w") as f:
                    f.write(full)
                print(f"Saved full results ({len(full)} chars) to /tmp/polk_post_results.html")

                # Count rows
                import re
                trs = re.findall(r'<tr class="(?:odd|even)Row">', full)
                print(f"Result rows (oddRow/evenRow): {len(trs)}")
                details = re.findall(r'taxdetail\.php\?id=(\d+)', full)
                print(f"taxdetail links: {len(details)}")
                if details:
                    print(f"  First 5 IDs: {details[:5]}")
        except Exception as e:
            print(f"Parse error: {e}")

    finally:
        try:
            browser.stop()
        except BaseException:
            pass

asyncio.run(test())
