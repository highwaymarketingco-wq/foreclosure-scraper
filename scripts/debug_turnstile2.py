"""Debug Turnstile on nccash.gov — try with stealth flags."""
import asyncio
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        await page.goto(
            "https://unclaimed.nccash.gov/app/claim-search", timeout=60000
        )
        await asyncio.sleep(10)

        # Check iframes
        iframes = await page.evaluate(
            """() => Array.from(document.querySelectorAll('iframe')).map(f => ({
                src: f.src || '', title: f.title || '', id: f.id || ''
            }))"""
        )
        print("IFRAMES:")
        for f in iframes:
            print(f"  {f}")

        # Check turnstile token
        ts1 = await page.evaluate(
            """() => {
                const el = document.querySelector('[name="cf-turnstile-response"]');
                return el ? {value: el.value.substring(0, 20) + '...', len: el.value.length} : null;
            }"""
        )
        print(f"\nTurnstile at 10s: {ts1}")

        # Check all script tags — is Turnstile JS loaded?
        scripts = await page.evaluate(
            """() => Array.from(document.querySelectorAll('script')).map(s => s.src).filter(s => s.length > 0)"""
        )
        print(f"\nScript srcs: {len(scripts)}")
        for s in scripts:
            if "turnstile" in s or "cloudflare" in s or "challenge" in s:
                print(f"  CF/Turnstile: {s}")

        # Check for cf-turnstile div content
        cf_div = await page.evaluate(
            """() => {
                const el = document.querySelector('.cf-turnstile, [data-sitekey], [class*="turnstile"]');
                if (!el) return null;
                return {
                    tag: el.tagName, class: el.className,
                    sitekey: el.getAttribute('data-sitekey'),
                    html: el.innerHTML.substring(0, 300),
                    children: el.children.length
                };
            }"""
        )
        print(f"\nCF Turnstile div: {cf_div}")

        # Wait 30 more seconds
        print("\nWaiting 30 more seconds...")
        await asyncio.sleep(30)
        ts2 = await page.evaluate(
            """() => {
                const el = document.querySelector('[name="cf-turnstile-response"]');
                return el ? {value: el.value.substring(0, 20) + '...', len: el.value.length} : null;
            }"""
        )
        print(f"Turnstile at 40s: {ts2}")

        # Check iframes again
        iframes2 = await page.evaluate(
            """() => Array.from(document.querySelectorAll('iframe')).map(f => ({
                src: f.src.substring(0, 100), title: f.title || ''
            }))"""
        )
        print(f"\nIframes at 40s: {len(iframes2)}")
        for f in iframes2:
            print(f"  {f}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(check())
