"""Debug: Polk County NC delinquent tax search via nodriver.

Target: cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php
Form fields: ReportGroupDescription, TaxYear, BalanceDue, SearchColumn, SearchText
POST target: searchingtaxrecord.php

nodriver = undetected Chrome that defeats Cloudflare bot detection.
"""
import asyncio
import os
import re
import sys

import httpx

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"
POST_URL = "https://cms.revize.com/revize/apps/polkcounty/searchingtaxrecord.php"

# Row regex — tested against real captured HTML
_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>(?P<name>[^<]+)</td>\s*'
    r'<td[^>]*>(?P<parcel>[^<]+)</td>\s*'
    r'<td[^>]*>(?P<address>[^<]+)</td>\s*'
    r'<td[^>]*>(?P<amount>[^<]+)</td>\s*'
    r'<td[^>]*>(?P<link><a[^>]*href="[^"]*"[^>]*>[^<]*</a>)</td>\s*'
    r'</tr>',
    re.I | re.S,
)


async def main():
    try:
        import nodriver as uc
    except ImportError:
        print("ERROR: nodriver not installed")
        return

    print("Starting nodriver browser...")
    browser = await uc.start(
        headless=False,
        browser_args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        sandbox=False,
    )

    page = await browser.get("about:blank")

    # Navigate to search page
    print(f"Loading: {SEARCH_URL}")
    await page.get(SEARCH_URL)
    await asyncio.sleep(8)

    # Check page content
    content = await page.get_content()
    print(f"Page content length: {len(content)}")

    # Check for Cloudflare block
    if "sorry, you have been blocked" in content.lower():
        print("BLOCKED: Cloudflare bot detection")
        # Save for analysis
        with open("/tmp/polk_blocked.html", "w") as f:
            f.write(content)
        print("Blocked page saved to /tmp/polk_blocked.html")
    elif "searchtaxrecord" in content.lower() or "tax year" in content.lower():
        print("SEARCH PAGE LOADED!")
        with open("/tmp/polk_search_page.html", "w") as f:
            f.write(content)
        print("Search page saved to /tmp/polk_search_page.html")

        # Fill search form — search for common surname "Smith"
        try:
            # Find search text field
            search_text = await page.find("SearchText", best_match=True)
            if search_text:
                await search_text.send_keys("Smith")
                print("Filled SearchText: Smith")
        except Exception as e:
            print(f"SearchText fill error: {e}")
            # Try by selector
            try:
                el = await page.query_selector("input[name='SearchText']")
                if el:
                    await el.send_keys("Smith")
                    print("Filled SearchText via selector: Smith")
            except Exception as e2:
                print(f"SearchText selector error: {e2}")

        # Click search button
        try:
            search_btn = await page.find("Search", best_match=True)
            if search_btn:
                await search_btn.click()
                print("Search clicked")
        except Exception as e:
            print(f"Search button error: {e}")

        await asyncio.sleep(8)

        # Get results
        results_content = await page.get_content()
        print(f"Results content length: {len(results_content)}")

        # Parse rows
        matches = _ROW_RE.findall(results_content)
        print(f"Parsed rows: {len(matches)}")

        with open("/tmp/polk_results.html", "w") as f:
            f.write(results_content)
        print("Results saved to /tmp/polk_results.html")

    else:
        print(f"UNKNOWN page content (first 500 chars):")
        print(content[:500])
        with open("/tmp/polk_unknown.html", "w") as f:
            f.write(content)

    # Also try POST directly via browser fetch (same-origin)
    print(f"\nTrying same-origin POST to {POST_URL}...")
    try:
        post_result = await page.evaluate(f"""async () => {{
            const resp = await fetch('{POST_URL}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                body: 'ReportGroupDescription=&TaxYear=&BalanceDue=&SearchColumn=Name&SearchText=Smith'
            }});
            return await resp.text();
        }}""")
        print(f"POST result length: {len(post_result)}")
        if "sorry, you have been blocked" in post_result.lower():
            print("POST BLOCKED: Cloudflare")
        else:
            matches = _ROW_RE.findall(post_result)
            print(f"POST parsed rows: {len(matches)}")
        with open("/tmp/polk_post_results.html", "w") as f:
            f.write(post_result)
        print("POST results saved to /tmp/polk_post_results.html")
    except Exception as e:
        print(f"POST error: {e}")

    # Take screenshot
    try:
        await page.save_screenshot("/tmp/polk_nodriver.png")
        print("Screenshot saved to /tmp/polk_nodriver.png")
    except Exception as e:
        print(f"Screenshot error: {e}")

    browser.stop()


asyncio.run(main())
