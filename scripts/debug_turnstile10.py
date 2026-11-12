"""Debug: Turnstile v10 - minimal HTML page with Turnstile widget.

Instead of loading the Angular SPA and injecting, create a minimal HTML
page with just the Turnstile widget. This avoids Angular's detection.
Also checks if window.turnstile is actually available after script load.
"""
import asyncio
import httpx
from patchright.async_api import async_playwright

SITEKEY = "0x4AAAAAAAhrAOTfac6OZIll"
PAGE_URL = "https://unclaimed.nccash.gov/app/claim-search"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        # Navigate to the real page first (so origin matches for Turnstile)
        print("Loading real page...")
        await page.goto(PAGE_URL, timeout=60000)
        await asyncio.sleep(8)

        # Check if turnstile is already loaded from the page
        ts_available = await page.evaluate("() => typeof window.turnstile !== 'undefined'")
        print(f"turnstile already loaded: {ts_available}")

        if not ts_available:
            # Inject the Turnstile script
            print("Injecting Turnstile JS...")
            await page.add_script_tag(url="https://challenges.cloudflare.com/turnstile/v0/api.js")
            # Wait for it to load
            for i in range(10):
                await asyncio.sleep(1)
                ts_available = await page.evaluate("() => typeof window.turnstile !== 'undefined'")
                if ts_available:
                    print(f"Turnstile loaded after {i+1}s")
                    break
            else:
                print("Turnstile JS never loaded!")
                await browser.close()
                return

        # Check what methods are available
        methods = await page.evaluate("""() => {
            if (!window.turnstile) return [];
            return Object.keys(window.turnstile);
        }""")
        print(f"Turnstile methods: {methods}")

        # Create container and render widget
        print("Rendering Turnstile widget...")
        await page.evaluate(f"""() => {{
            // Remove existing widgets
            document.querySelectorAll('[id^="cf-chl-widget"]').forEach(e => e.remove());

            // Create container
            const container = document.createElement('div');
            container.id = 'ts-container';
            container.style.position = 'fixed';
            container.style.top = '50%';
            container.style.left = '50%';
            container.style.transform = 'translate(-50%, -50%)';
            document.body.appendChild(container);

            // Render widget
            window.turnstile.render('#ts-container', {{
                sitekey: '{SITEKEY}',
                callback: function(token) {{
                    window.__ts_token = token;
                    console.log('TOKEN RECEIVED:', token.substring(0, 30) + '...');
                }},
                'error-callback': function(err) {{
                    window.__ts_error = err;
                    console.log('TURNSTILE ERROR:', err);
                }},
                'expired-callback': function() {{
                    window.__ts_expired = true;
                }},
                'timeout-callback': function() {{
                    window.__ts_timeout = true;
                }},
            }});
        }}""")

        # Wait for token, check for errors
        token = None
        for i in range(45):
            await asyncio.sleep(2)
            result = await page.evaluate("""() => ({
                token: window.__ts_token || null,
                error: window.__ts_error || null,
                expired: window.__ts_expired || false,
                timeout: window.__ts_timeout || false,
                widgetHTML: (document.querySelector('#ts-container') || {{}}).innerHTML?.substring(0, 200) || 'no container',
                widgetLen: (document.querySelector('#ts-container') || {{}}).innerHTML?.length || 0,
                iframes: document.querySelectorAll('iframe').length,
            })""")

            if result.get('token'):
                token = result['token']
                print(f"\nGOT TOKEN at {i*2}s: {token[:60]}...")
                break

            if result.get('error'):
                print(f"  {i*2}s: ERROR: {result['error']}")

            if i % 5 == 0:
                print(f"  {i*2}s: no token, widget_len={result.get('widgetLen', 0)}, iframes={result.get('iframes', 0)}, html={result.get('widgetHTML', '')[:80]}")

        if not token:
            print("\nNO TOKEN after 90s")
            # List all iframes on page
            iframes = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('iframe')).map(f => ({
                    src: f.src?.substring(0, 100),
                    id: f.id,
                    name: f.name,
                }));
            }""")
            print(f"Iframes on page: {iframes}")
            await page.screenshot(path="/tmp/ts10_final.png")
            print("Screenshot saved to /tmp/ts10_final.png")
            await browser.close()
            return

        # Use the token with the API
        print("\nUsing token with API...")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://unclaimed.nccash.gov/SWS/properties",
                json={
                    "surName": "Smith",
                    "firstName": "",
                    "city": "",
                    "state": "",
                    "zip": "",
                    "propertyType": "",
                    "turnstileToken": token,
                },
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://unclaimed.nccash.gov",
                    "Referer": "https://unclaimed.nccash.gov/app/claim-search",
                },
                timeout=30,
            )
            print(f"API response: {resp.status_code}")
            print(f"Body: {resp.text[:500]}")

        await browser.close()


asyncio.run(main())
