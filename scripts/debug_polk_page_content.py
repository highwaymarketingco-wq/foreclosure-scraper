"""Debug: Check what nodriver sees on Polk search page (headless=False)."""
import asyncio
from foreclosure_scraper.browser_utils import start_browser

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"

async def test():
    browser = await start_browser(headless=False)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(12)
        html = await page.get_content()
        print(f"Page length: {len(html)}")
        print(f"Contains SearchText: {'SearchText' in html}")
        print(f"Contains form: {'<form' in html.lower()}")
        print(f"Contains iframe: {'iframe' in html.lower()}")
        print(f"Contains blocked: {'blocked' in html.lower()}")
        print(f"Contains just a moment: {'just a moment' in html.lower()}")
        print(f"Contains challenge: {'challenge' in html.lower()}")
        # Save for inspection
        with open("/tmp/polk_headless_false.html", "w") as f:
            f.write(html)
        print("Saved to /tmp/polk_headless_false.html")
        # Print first 800 chars
        print("---FIRST 800---")
        print(html[:800])
    finally:
        try:
            browser.stop()
        except BaseException:
            pass

asyncio.run(test())
