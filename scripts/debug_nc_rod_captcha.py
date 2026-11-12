"""Debug: NC ROD captcha counties — test patchright on 7 reCAPTCHA counties.

Counties: wake, durham, iredell, greene, harnett, stokes, + brunswick (math)
Gate types: recaptcha (7), math (1: brunswick)

Strategy: patchright may auto-solve reCAPTCHA checkbox on some sites.
If not, try the Lexington vision approach.
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, "src")
os.environ.setdefault("DISPLAY", ":99")

from patchright.async_api import async_playwright

COUNTIES = {
    "wake": {"url": "https://rodrecords.wake.gov", "gate": "recaptcha", "search_path": "/search/deeds"},
    "durham": {"url": "https://rodrecords.durhamcountync.gov", "gate": "recaptcha", "search_path": "/search/deeds"},
    "iredell": {"url": "https://rod.iredellcountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "greene": {"url": "https://rod.greenecountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "harnett": {"url": "https://rod.harnettcountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "stokes": {"url": "https://rod.stokescountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "brunswick": {"url": "https://rodrecords.brunswickcountync.gov", "gate": "math", "search_path": "/search/deeds"},
}


async def test_county(browser, name, config):
    """Test one county."""
    url = config["url"] + config["search_path"]
    gate = config["gate"]
    print(f"\n{'='*50}")
    print(f"County: {name} (gate: {gate})")
    print(f"URL: {url}")
    print(f"{'='*50}")

    ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()

    try:
        await page.goto(url, timeout=45000)
        await asyncio.sleep(5)

        content = await page.content()
        print(f"  Page loaded: {len(content)} chars")

        # Check for reCAPTCHA
        has_recaptcha = "g-recaptcha" in content.lower() or "recaptcha" in content.lower()
        has_math = "math" in content.lower() and ("question" in content.lower() or "solve" in content.lower())

        if has_recaptcha:
            print("  reCAPTCHA found — trying checkbox click")
            recaptcha_frame = None
            for frame in page.frames:
                if "recaptcha/api2/anchor" in frame.url:
                    recaptcha_frame = frame
                    break

            if recaptcha_frame:
                try:
                    await recaptcha_frame.click(".recaptcha-checkbox-border")
                    print("  Clicked checkbox")
                    await asyncio.sleep(5)

                    token = await page.evaluate(
                        "() => document.getElementById('g-recaptcha-response')?.value || ''"
                    )
                    if token:
                        print(f"  AUTO-SOLVED! Token: {token[:60]}...")
                        # Try searching
                        search_input = await page.query_selector("input[type='text'], input[name*='name'], input[name*='search']")
                        if search_input:
                            await search_input.fill("Smith")
                            print("  Filled search: Smith")

                        search_btn = await page.query_selector("input[type='submit'], button[type='submit'], .search-btn")
                        if search_btn:
                            await search_btn.click()
                            print("  Clicked search")
                            await asyncio.sleep(8)
                            results = await page.content()
                            print(f"  Results page: {len(results)} chars")
                            with open(f"/tmp/nc_rod_{name}_results.html", "w") as f:
                                f.write(results)
                            print(f"  Saved to /tmp/nc_rod_{name}_results.html")
                    else:
                        print("  Not auto-solved — visual challenge appeared")
                        # Check for challenge frame
                        for frame in page.frames:
                            if "recaptcha/api2/bframe" in frame.url:
                                print("  Challenge frame found (needs vision solver)")
                                break
                except Exception as e:
                    print(f"  Checkbox error: {e}")
            else:
                print("  No reCAPTCHA anchor frame found")

        elif has_math:
            print("  Math CAPTCHA found — trying to solve")
            # Extract math question
            math_text = await page.evaluate("""() => {
                const body = document.body.innerText;
                const match = body.match(/(\\d+)\\s*([+\\-*/])\\s*(\\d+)\\s*=\\s*\\??/);
                return match ? match[0] : '';
            }""")
            if math_text:
                print(f"  Math question: {math_text}")
                # Solve it
                parts = re.match(r'(\d+)\s*([+\-*/])\s*(\d+)', math_text)
                if parts:
                    a, op, b = int(parts.group(1)), parts.group(2), int(parts.group(3))
                    if op == '+': answer = a + b
                    elif op == '-': answer = a - b
                    elif op == '*': answer = a * b
                    elif op == '/': answer = a // b
                    print(f"  Answer: {answer}")

                    # Fill answer
                    answer_input = await page.query_selector("input[name*='answer'], input[name*='captcha'], input[name*='math']")
                    if answer_input:
                        await answer_input.fill(str(answer))
                        print(f"  Filled answer: {answer}")
                        # Submit
                        submit = await page.query_selector("input[type='submit'], button[type='submit']")
                        if submit:
                            await submit.click()
                            await asyncio.sleep(5)
                            results = await page.content()
                            print(f"  After submit: {len(results)} chars")
                            with open(f"/tmp/nc_rod_{name}_results.html", "w") as f:
                                f.write(results)
            else:
                print("  Could not extract math question")

        elif "search" in content.lower():
            print("  NO CAPTCHA — search page directly accessible!")
            # Try searching
            search_input = await page.query_selector("input[type='text'], input[name*='name'], input[name*='search']")
            if search_input:
                await search_input.fill("Smith")
                search_btn = await page.query_selector("input[type='submit'], button[type='submit']")
                if search_btn:
                    await search_btn.click()
                    await asyncio.sleep(8)
                    results = await page.content()
                    print(f"  Results: {len(results)} chars")
                    with open(f"/tmp/nc_rod_{name}_results.html", "w") as f:
                        f.write(results)

        else:
            print(f"  Unknown page (first 300 chars):")
            print(content[:300])

    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        await ctx.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )

        for name, config in COUNTIES.items():
            await test_county(browser, name, config)
            await asyncio.sleep(3)

        await browser.close()
    print("\n=== ALL ROD COUNTIES TESTED ===")


asyncio.run(main())
