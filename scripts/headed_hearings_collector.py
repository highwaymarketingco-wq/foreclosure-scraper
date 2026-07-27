#!/usr/bin/env python3
"""Headed Search Hearings collector - user solves CAPTCHA, script sweeps counties."""
import asyncio
import os
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

REPO = "/Users/cashhigh/foreclosure-scraper"
TARGET_COUNTIES = [
    "Buncombe", "Henderson", "Cleveland", "Gaston", "Rutherford",
    "Polk", "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke",
    "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
]


async def safe_content(page):
    try:
        return await page.content()
    except Exception:
        await asyncio.sleep(2)
        try:
            return await page.content()
        except Exception:
            return ""


async def wait_for_captcha(page, label="", timeout_s=600):
    for attempt in range(timeout_s // 5):
        await asyncio.sleep(5)
        content = await safe_content(page)
        if "txtHSLastName" in content or "selHSCourtroom" in content:
            print(f"  [SOLVED] {label} ({(attempt+1)*5}s)")
            return True
        if attempt % 6 == 0:
            try:
                title = await page.title()
            except:
                title = "?"
            print(f"  [{(attempt+1)*5}s] Waiting for CAPTCHA... title: \"{title}\"")
    print(f"  [TIMEOUT] {label}")
    return False


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False, slow_mo=300,
            args=["--disable-blink-features=AutomationControlled",
                  "--window-position=0,0", "--window-size=1400,900"],
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/145.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()

        print("=== NC SEARCH HEARINGS ===")
        print("Separate Chromium window opening. SOLVE THE CAPTCHA.")
        print()

        await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/26",
                        wait_until="domcontentloaded", timeout=60000)

        if not await wait_for_captcha(page, "Search Hearings"):
            await browser.close()
            return

        # Print available courtroom options
        courtrooms = await page.evaluate("""() => {
            const sel = document.querySelector('#selHSCourtroom');
            if (!sel) return [];
            return [...sel.options].map(o => ({value: o.value, text: o.text.trim()}));
        }""")
        print(f"\nAvailable courtrooms: {len(courtrooms)}")
        for cr in courtrooms[:40]:
            print(f"  {cr['value']}: {cr['text']}")

        date_from = datetime.now().strftime("%m/%d/%Y")
        date_to = (datetime.now() + timedelta(days=90)).strftime("%m/%d/%Y")
        print(f"\nDate range: {date_from} to {date_to} (next 90 days)")

        total = 0
        for county in TARGET_COUNTIES:
            filename = os.path.join(REPO, f"nc_hearings_{county.lower()}.html")
            if os.path.exists(filename):
                print(f"\n  SKIP {county} (exists)")
                continue

            print(f"\n  Searching: {county}...")
            try:
                await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/26",
                                wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                content = await safe_content(page)
                if "confirm you are human" in content.lower():
                    print("    CAPTCHA appeared. Solve it in the window...")
                    if not await wait_for_captcha(page, f"{county}"):
                        continue

                # Select courtroom matching county
                selected = await page.evaluate("""(county) => {
                    const sel = document.querySelector('#selHSCourtroom');
                    if (!sel) return false;
                    for (const o of sel.options) {
                        if (o.text.toLowerCase().includes(county.toLowerCase())) {
                            sel.value = o.value;
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                            return o.text;
                        }
                    }
                    return false;
                }""", county)

                if selected:
                    print(f"    Courtroom: {selected}")
                else:
                    print(f"    County not in dropdown")

                # Set date range
                await page.evaluate(f"""() => {{
                    const f = document.querySelector('#SearchCriteria_DateFrom');
                    const t = document.querySelector('#SearchCriteria_DateTo');
                    if (f) f.value = {date_from!r};
                    if (t) t.value = {date_to!r};
                }}""")

                # Clear name fields
                await page.evaluate("""() => {
                    const ln = document.querySelector('#txtHSLastName');
                    const fn = document.querySelector('#txtHSFirstName');
                    if (ln) ln.value = '';
                    if (fn) fn.value = '';
                }""")

                # Submit
                await page.evaluate("""() => {
                    const btn = document.querySelector('#btnHSSubmit');
                    if (btn) btn.click();
                }""")

                # Wait for results to load
                await asyncio.sleep(10)

                # Check for CAPTCHA after submit
                content = await safe_content(page)
                if "confirm you are human" in content.lower():
                    print("    CAPTCHA after submit. Solve it...")
                    if not await wait_for_captcha(page, f"{county} post-submit"):
                        continue
                    content = await safe_content(page)

                if len(content) > 5000:
                    with open(filename, "w") as f:
                        f.write(content)
                    print(f"    SAVED ({len(content)} bytes)")
                    total += 1
                elif "no hearings" in content.lower() or "no cases" in content.lower():
                    print(f"    No hearings")
                else:
                    print(f"    Too short ({len(content)} bytes)")

                await asyncio.sleep(2)

            except Exception as e:
                print(f"    ERROR: {e}")

        print(f"\n=== DONE: {total} hearing files saved ===")
        print("Keeping browser open 5 min.")
        await asyncio.sleep(300)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
