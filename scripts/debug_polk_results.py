"""Debug: Save Polk search results for letter 'b' to inspect HTML structure."""
import asyncio
from foreclosure_scraper.scrapers.counties_nc.polk_tax import _search_via_nodriver
from foreclosure_scraper.browser_utils import start_browser

async def test():
    browser = await start_browser(headless=False)
    try:
        html = await _search_via_nodriver(browser, "b")
        print(f"Results page: {len(html)} chars")
        with open("/tmp/polk_results_b.html", "w") as f:
            f.write(html)
        print("Saved to /tmp/polk_results_b.html")

        # Check for table rows
        import re
        trs = re.findall(r'<tr[^>]*>.*?</tr>', html, re.S)
        print(f"Found {len(trs)} <tr> elements")
        for i, tr in enumerate(trs[:5]):
            print(f"  Row {i}: {tr[:200]}")

        # Check for common result indicators
        for pattern in ["oddRow", "evenRow", "taxdetail", "Result", "No results", "no match", "No records"]:
            count = html.lower().count(pattern.lower())
            if count > 0:
                print(f"  '{pattern}': {count}")
    finally:
        try:
            browser.stop()
        except BaseException:
            pass

asyncio.run(test())
