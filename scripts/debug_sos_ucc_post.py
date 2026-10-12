"""Debug: Try direct POST to NC SOS UCC results endpoint via nodriver browser context.

The page at by_title/_uniform_commercial_code is actually a business registration
search. The real UCC search results endpoint is:
  /online_services/search/_Uniform_Commercial_Code_Results

We'll load the search page in nodriver, extract the __RequestVerificationToken,
then POST to the UCC results endpoint from the browser context.
"""
import asyncio
import sys
sys.path.insert(0, "src")

from foreclosure_scraper.browser_utils import start_browser

SEARCH_PAGE_URL = "https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code"
UCC_RESULTS_URL = "https://www.sosnc.gov/online_services/search/_Uniform_Commercial_Code_Results"

async def main():
    browser = await start_browser(headless=True)

    try:
        page = await browser.get(SEARCH_PAGE_URL)
        await asyncio.sleep(8)  # wait for Cloudflare + page load

        html = await page.get_content()
        print(f"Search page loaded: {len(html)} chars")

        # Extract verification token
        import re
        token_match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', html)
        token = token_match.group(1) if token_match else ""
        print(f"Token found: {bool(token)} ({token[:30]}...)")

        # Try POST to UCC results endpoint from browser context
        # The form fields: CorpSearchType, EntityType, Words, SearchCriteria, etc.
        js_fetch = f"""
        (async () => {{
            const formData = new URLSearchParams();
            formData.append("CorpSearchType", "UCC");
            formData.append("SearchCriteria", "a");
            formData.append("Words", "STARTING");
            formData.append("__RequestVerificationToken", "{token}");

            const resp = await fetch("{UCC_RESULTS_URL}", {{
                method: "POST",
                headers: {{"Content-Type": "application/x-www-form-urlencoded"}},
                body: formData.toString(),
                redirect: "follow",
            }});
            const text = await resp.text();
            return JSON.stringify({{status: resp.status, length: text.length, snippet: text.substring(0, 500)}});
        }})()
        """

        result = await page.evaluate(js_fetch, await_promise=True)
        print(f"UCC Results POST: {result}")

        # Also try GET to the UCC results URL with search params
        js_get = f"""
        (async () => {{
            const resp = await fetch("{UCC_RESULTS_URL}?SearchCriteria=a&Words=STARTING", {{
                method: "GET",
                redirect: "follow",
            }});
            const text = await resp.text();
            return JSON.stringify({{status: resp.status, length: text.length, snippet: text.substring(0, 500)}});
        }})()
        """

        result2 = await page.evaluate(js_get, await_promise=True)
        print(f"UCC Results GET: {result2}")

    finally:
        try:
            browser.stop()
        except BaseException:
            pass

asyncio.run(main())
