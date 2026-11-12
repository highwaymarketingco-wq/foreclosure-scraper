"""Debug: Use scrapling with page_action to fill and submit the NC SOS UCC form.

The page at by_title/_uniform_commercial_code has a form that posts to
Business_Registration_Results — but the real UCC search is a different form
on a different page. Let's try loading the page, changing CorpSearchType to
see if there's a UCC option, and submitting.

Actually — let's just use scrapling to load the page, fill the form, and
submit. The key insight: SubmitMainFormView() in Search_Business_Registration.js
handles the form submission. We need to click the actual SubmitButton.
"""
import asyncio
from scrapling.fetchers import StealthyFetcher

SEARCH_URL = "https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code"

async def page_action(page):
    """Fill search form and submit."""
    try:
        # Wait for the search input
        await page.wait_for_selector("#SearchCriteria", timeout=20000)
        print("Found SearchCriteria input")

        # Fill with 'a' for broad search
        await page.fill("#SearchCriteria", "a")
        print("Filled SearchCriteria with 'a'")

        # Check what CorpSearchType options are available
        options = await page.query_selector_all("#CorpSearchType option")
        for opt in options:
            val = await opt.get_attribute("value")
            text = await opt.text_content()
            print(f"  CorpSearchType option: {val} = {text}")

        # Click the SubmitButton (it's type=button, calls SubmitMainFormView)
        await page.click("#SubmitButton", timeout=10000)
        print("Clicked SubmitButton")

        # Wait for results page to load
        await page.wait_for_load_state("networkidle", timeout=30000)
        print("Network idle — results should be loaded")

    except Exception as e:
        print(f"page_action error: {e}")

async def main():
    result = await asyncio.wait_for(
        StealthyFetcher.async_fetch(
            SEARCH_URL, headless=True, network_idle=True,
            timeout=90000, page_action=page_action,
            solve_cloudflare=True,
        ),
        timeout=120,
    )

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    status = getattr(result, "status", "?")
    url = getattr(result, "url", "?")

    print(f"\nFinal URL: {url}")
    print(f"Status: {status}, Length: {len(html)}")

    # Save HTML for inspection
    with open("/tmp/sos_ucc_form_submit.html", "w") as f:
        f.write(html)
    print("Saved to /tmp/sos_ucc_form_submit.html")

    # Check for results indicators
    for pattern in ["debtor", "secured", "filing", "result", "no results", "no match", "UCC"]:
        count = html.lower().count(pattern.lower())
        if count > 0:
            print(f"  '{pattern}': {count} occurrences")

asyncio.run(main())
