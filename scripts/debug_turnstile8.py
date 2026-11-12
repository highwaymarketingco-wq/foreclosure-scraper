"""Debug: Click SEARCH to trigger Turnstile modal, extract sitekey, intercept network."""
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
        
        # Intercept network requests to find config API
        config_responses = []
        async def on_response(response):
            url = response.url
            if "config" in url.lower() or "appconfig" in url.lower() or "SWS/app" in url:
                try:
                    body = await response.text()
                    config_responses.append({"url": url, "body": body[:1000]})
                except:
                    config_responses.append({"url": url, "body": "<error>"})
        
        page.on("response", on_response)
        
        await page.goto("https://unclaimed.nccash.gov/app/claim-search", timeout=60000)
        await asyncio.sleep(10)
        
        # Fill in a search term
        try:
            await page.fill("input[name='surName'], input[name='lastName'], input[placeholder*='Name'], input[type='text']", "Smith")
            await asyncio.sleep(1)
        except:
            # Try JS
            await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input[type="text"]');
                if (inputs.length > 0) {
                    inputs[0].value = 'Smith';
                    inputs[0].dispatchEvent(new Event('input', {bubbles: true}));
                }
            }""")
            await asyncio.sleep(1)
        
        # Click SEARCH button
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const text = (b.innerText || b.textContent || '').toUpperCase();
                if (text.includes('SEARCH')) {
                    b.click();
                    return 'clicked: ' + text;
                }
            }
            return 'no search button found';
        }""")
        
        await asyncio.sleep(10)
        
        # Now look for Turnstile widget in the modal
        ts_info = await page.evaluate("""() => {
            const result = {widgets: [], iframes: [], config: null};
            
            // Check for Turnstile widgets
            const widgets = document.querySelectorAll('[id^="cf-chl-widget"]');
            for (const w of widgets) {
                result.widgets.push({
                    id: w.id,
                    sitekey: w.getAttribute('data-sitekey'),
                    innerHTML_len: w.innerHTML.length,
                });
            }
            
            // Check all iframes
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                const src = iframe.getAttribute('src') || '';
                result.iframes.push({
                    src: src.substring(0, 300),
                    title: iframe.getAttribute('title'),
                });
            }
            
            return result;
        }""")
        print(f"Turnstile after SEARCH: {ts_info}")
        print(f"Config responses: {config_responses}")
        
        # Wait longer for modal to render
        await asyncio.sleep(10)
        
        ts_info2 = await page.evaluate("""() => {
            const result = {widgets: [], iframes: []};
            const widgets = document.querySelectorAll('[id^="cf-chl-widget"]');
            for (const w of widgets) {
                result.widgets.push({
                    id: w.id,
                    sitekey: w.getAttribute('data-sitekey'),
                    innerHTML_len: w.innerHTML.length,
                    innerHTML_start: w.innerHTML.substring(0, 200),
                });
            }
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                const src = iframe.getAttribute('src') || '';
                if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenge')) {
                    result.iframes.push({
                        src: src.substring(0, 500),
                        title: iframe.getAttribute('title'),
                    });
                }
            }
            return result;
        }""")
        print(f"Turnstile after 20s: {ts_info2}")
        
        await browser.close()


asyncio.run(main())
