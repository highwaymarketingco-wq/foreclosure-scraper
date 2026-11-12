"""Debug: Morganton NC + City of Union SC WAF diagnostics.

Check if enrichment_waf_oss.solve_waf_via_browser actually clears the
Cloudflare challenge, or if we're getting the interstitial page content
instead of the real page.
"""
import asyncio
import re
from patchright.async_api import async_playwright

TARGETS = [
    ("morganton_condemned", "https://www.morgantonnc.gov/government/code-enforcement/condemned-properties"),
    ("morganton_code_enf", "https://www.morgantonnc.gov/government/code-enforcement"),
    ("morganton_tax_fore", "https://www.morgantonnc.gov/government/tax/tax-foreclosures"),
    ("union_tax", "https://www.cityofunion.net/departments/finance/tax"),
    ("union_building", "https://www.cityofunion.net/departments/building-codes"),
    ("union_news", "https://www.cityofunion.net/news"),
]

CF_INTERSTITIAL_PATTERNS = [
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "challenge-platform",
    "turnstile",
    "cf-turnstile",
    "attention required",
    "sorry, you have been blocked",
]

REAL_CONTENT_INDICATORS = [
    "condemned",
    "foreclosure",
    "tax",
    "property",
    "department",
    "government",
    "code enforcement",
    "building",
    "news",
    "meeting",
    "agenda",
    "ordinance",
]


async def check_url(page, name, url):
    print(f"\n{'='*60}")
    print(f"Checking: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")

    try:
        await page.goto(url, timeout=45000)
    except Exception as e:
        print(f"  Navigation error: {e}")
        return

    await asyncio.sleep(3)

    # Get page content BEFORE WAF solve
    content_before = await page.content()
    title_before = await page.title()
    print(f"  Before WAF solve:")
    print(f"    Title: {title_before}")
    print(f"    Content length: {len(content_before)}")

    # Check for CF interstitial indicators
    cf_hits_before = [p for p in CF_INTERSTITIAL_PATTERNS if p.lower() in content_before.lower()]
    real_hits_before = [p for p in REAL_CONTENT_INDICATORS if p.lower() in content_before.lower()]
    print(f"    CF indicators: {cf_hits_before}")
    print(f"    Real content indicators: {real_hits_before}")

    # Try WAF solve
    try:
        from foreclosure_scraper.enrichment_waf_oss import solve_waf_via_browser
        solved = await solve_waf_via_browser(page)
        print(f"  WAF solve returned: {solved}")
    except Exception as e:
        print(f"  WAF solve error: {e}")
        solved = False

    await asyncio.sleep(3)

    # Get page content AFTER WAF solve
    content_after = await page.content()
    title_after = await page.title()
    print(f"  After WAF solve:")
    print(f"    Title: {title_after}")
    print(f"    Content length: {len(content_after)}")

    cf_hits_after = [p for p in CF_INTERSTITIAL_PATTERNS if p.lower() in content_after.lower()]
    real_hits_after = [p for p in REAL_CONTENT_INDICATORS if p.lower() in content_after.lower()]
    print(f"    CF indicators: {cf_hits_after}")
    print(f"    Real content indicators: {real_hits_after}")

    # Verdict
    if cf_hits_after and not real_hits_after:
        print(f"  VERDICT: STILL BLOCKED (CF interstitial)")
    elif real_hits_after:
        print(f"  VERDICT: REAL PAGE LOADED")
        # Save content for analysis
        safe_name = name.replace(" ", "_")
        with open(f"/tmp/waf_{safe_name}.html", "w") as f:
            f.write(content_after)
        print(f"  Content saved to /tmp/waf_{safe_name}.html")

        # Check for listing data
        listings = re.findall(r'<tr|<li|<div class="(?:property|listing|record)', content_after, re.I)
        print(f"  Potential listing elements: {len(listings)}")
    else:
        print(f"  VERDICT: UNCLEAR (no CF indicators, no real content)")

    # Screenshot
    safe_name = name.replace(" ", "_")
    await page.screenshot(path=f"/tmp/waf_{safe_name}.png")
    print(f"  Screenshot saved")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})

        for name, url in TARGETS:
            page = await ctx.new_page()
            await check_url(page, name, url)
            await page.close()

        await browser.close()


asyncio.run(main())
