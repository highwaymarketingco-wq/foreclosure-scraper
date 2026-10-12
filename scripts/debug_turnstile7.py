"""Debug: Extract Turnstile sitekey from rendered page."""
import asyncio
from patchright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()
        await page.goto("https://unclaimed.nccash.gov/app/claim-search", timeout=60000)
        await asyncio.sleep(15)

        # Get the sitekey from the rendered widget
        info = await page.evaluate("""() => {
            // Try data-sitekey attribute
            const w = document.querySelector('[data-sitekey]');
            if (w) return {sitekey: w.getAttribute('data-sitekey'), method: 'data-sitekey'};
            
            // Try from turnstile object
            try {
                const widgets = document.querySelectorAll('[id^="cf-chl-widget"]');
                for (const widget of widgets) {
                    const iframe = widget.querySelector('iframe');
                    if (iframe) {
                        const src = iframe.getAttribute('src') || '';
                        const match = src.match(/sitekey=([^&]+)/);
                        if (match) return {sitekey: match[1], method: 'iframe-src', widget_id: widget.id, src: src.substring(0, 200)};
                    }
                }
            } catch(e) {}
            
            // Try from all iframes
            const iframes = document.querySelectorAll('iframe');
            const iframeInfo = [];
            for (const iframe of iframes) {
                const src = iframe.getAttribute('src') || '';
                if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenge')) {
                    const match = src.match(/sitekey=([^&]+)/);
                    iframeInfo.push({
                        src: src.substring(0, 300),
                        sitekey: match ? match[1] : null,
                    });
                }
            }
            return {iframes: iframeInfo, method: 'iframe-scan'};
        }""")
        print(f"Turnstile info: {info}")

        # Also try to intercept network requests
        # Check if there's a config API call
        await browser.close()


asyncio.run(main())
