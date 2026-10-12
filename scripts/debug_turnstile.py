"""Debug Turnstile on nccash.gov — check if token auto-populates."""
import asyncio
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-gpu"]
        )
        page = await browser.new_page()
        await page.goto(
            "https://unclaimed.nccash.gov/app/claim-search", timeout=60000
        )
        await asyncio.sleep(8)

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
                return el ? {value: el.value, len: el.value.length} : null;
            }"""
        )
        print(f"\nTurnstile at 8s: {ts1}")

        # Wait 20 more seconds
        await asyncio.sleep(20)
        ts2 = await page.evaluate(
            """() => {
                const el = document.querySelector('[name="cf-turnstile-response"]');
                return el ? {value: el.value, len: el.value.length} : null;
            }"""
        )
        print(f"Turnstile at 28s: {ts2}")

        # Check visible Turnstile widget state
        widget = await page.evaluate(
            """() => {
                const container = document.querySelector('[class*="turnstile"]')
                    || document.querySelector('[id*="turnstile"]')
                    || document.querySelector('[class*="cf-turnstile"]');
                if (!container) return null;
                return {
                    html: container.innerHTML.substring(0, 500),
                    visible: container.offsetParent !== null
                };
            }"""
        )
        print(f"\nTurnstile widget: {widget}")

        # Try clicking search anyway and see what happens
        search_btn = page.locator("button:has-text('SEARCH')")
        if await search_btn.count() > 0:
            print("\nSEARCH button found, clicking...")
            await search_btn.first.click()
            await asyncio.sleep(5)

            # Check for error messages
            errors = await page.evaluate(
                """() => {
                    const texts = [];
                    document.querySelectorAll('*').forEach(el => {
                        const t = el.innerText || '';
                        if (t.length < 200 && (t.includes('rror') || t.includes('aptcha') || t.includes('uman'))) {
                            texts.push(t.trim());
                        }
                    });
                    return [...new Set(texts)].slice(0, 5);
                }"""
            )
            print(f"Error texts after click: {errors}")

            # Check URL for any redirect
            print(f"URL after click: {page.url}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(check())
