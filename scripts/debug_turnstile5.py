"""Debug Turnstile: load page, wait for auto-solve, try clicking checkbox."""
import asyncio
from patchright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        await page.goto("https://unclaimed.nccash.gov/app/claim-search", timeout=60000)

        # Wait for Turnstile to load and auto-solve
        token = None
        for i in range(30):
            await asyncio.sleep(2)
            token = await page.evaluate("""() => {
                try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                const el = document.querySelector('[name="cf-turnstile-response"]');
                if (el && el.value && el.value.length > 10) return el.value;
                return null;
            }""")
            if token:
                print(f"GOT TOKEN at {i*2}s: {token[:50]}...")
                break
            if i % 5 == 0:
                widgets = await page.evaluate("""() => {
                    const ws = document.querySelectorAll('[id^="cf-chl-widget"]');
                    return Array.from(ws).map(w => w.id);
                }""")
                print(f"  {i*2}s: no token, widgets={widgets}")

        if not token:
            print("NO TOKEN after 60s wait")

        # Try clicking search button
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.innerText && b.innerText.toUpperCase().includes('SEARCH')) {
                    b.click();
                    break;
                }
            }
        }""")
        await asyncio.sleep(10)
        token2 = await page.evaluate("""() => {
            try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
            const el = document.querySelector('[name="cf-turnstile-response"]');
            if (el && el.value && el.value.length > 10) return el.value;
            return null;
        }""")
        print(f"Token after SEARCH click: {token2}")

        await browser.close()


asyncio.run(main())
