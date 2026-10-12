"""Debug Turnstile v3 — try manual render + direct API call."""
import asyncio
import json
import httpx
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

        # Capture console messages
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text[:200]}"))

        await page.goto(
            "https://unclaimed.nccash.gov/app/claim-search", timeout=60000
        )
        await asyncio.sleep(8)

        # Check if window.turnstile exists
        ts_obj = await page.evaluate(
            """() => {
                if (typeof turnstile === 'undefined') return null;
                return {
                    exists: true,
                    methods: Object.keys(turnstile),
                    rendered: typeof turnstile.getResponse === 'function'
                };
            }"""
        )
        print(f"Turnstile object: {ts_obj}")

        # Look for sitekey anywhere on the page
        sitekey = await page.evaluate(
            """() => {
                // Check all elements for data-sitekey
                const els = document.querySelectorAll('[data-sitekey]');
                if (els.length > 0) return els[0].getAttribute('data-sitekey');
                
                // Check scripts for sitekey
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    const text = s.textContent || '';
                    const m = text.match(/sitekey['"\\s:=]+['"]([0-9a-zA-Z_x-]{20,})['"]/);
                    if (m) return m[1];
                }
                
                // Check Angular component data
                const app = document.querySelector('app-root');
                if (app) {
                    const html = app.innerHTML;
                    const m = html.match(/0x[0-9a-fA-F]{20,}/);
                    if (m) return m[0];
                }
                return null;
            }"""
        )
        print(f"Sitekey: {sitekey}")

        # Try to manually render Turnstile
        if ts_obj and ts_obj.get("exists"):
            print("\nAttempting manual turnstile.render()...")
            try:
                widget_id = await page.evaluate(
                    """() => {
                        // Create a div for turnstile
                        const div = document.createElement('div');
                        div.id = 'ts-manual';
                        document.body.appendChild(div);
                        
                        // Find sitekey from Angular app
                        // Try common NC sitekey patterns
                        return turnstile.render('#ts-manual', {
                            sitekey: '0x4AAAAAAAAjY2gE9K8b5gE9',
                            callback: function(token) {
                                window._ts_token = token;
                            }
                        });
                    }"""
                )
                print(f"Widget ID: {widget_id}")
            except Exception as e:
                print(f"Manual render failed: {e}")

        # Alternative: Try direct API call without Turnstile token
        print("\n--- Trying direct API call ---")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://unclaimed.nccash.gov/SWS/properties",
                    json={
                        "lastName": "Smith",
                        "firstName": "",
                        "city": "",
                        "searchZipCode": "",
                        "propertyID": "",
                        "cf-turnstile-response": "",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        "Origin": "https://unclaimed.nccash.gov",
                        "Referer": "https://unclaimed.nccash.gov/app/claim-search",
                    },
                    timeout=15,
                )
                print(f"API status: {resp.status_code}")
                print(f"API body: {resp.text[:500]}")
        except Exception as e:
            print(f"API call failed: {e}")

        # Try API call with a dummy token
        print("\n--- Trying API with dummy token ---")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://unclaimed.nccash.gov/SWS/properties",
                    json={
                        "lastName": "Smith",
                        "firstName": "",
                        "city": "",
                        "searchZipCode": "",
                        "propertyID": "",
                        "cf-turnstile-response": "dummy_token",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        "Origin": "https://unclaimed.nccash.gov",
                        "Referer": "https://unclaimed.nccash.gov/app/claim-search",
                    },
                    timeout=15,
                )
                print(f"API status: {resp.status_code}")
                print(f"API body: {resp.text[:500]}")
        except Exception as e:
            print(f"API call failed: {e}")

        # Check what the Angular app sends when searching
        print("\n--- Checking Angular app's API call format ---")
        # Intercept network requests
        api_calls = []

        async def on_request(request):
            if "/SWS/" in request.url:
                api_calls.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "post_data": request.post_data,
                })

        page.on("request", on_request)

        # Fill and try to search
        await page.fill("input[name='lastName']", "Smith")
        await asyncio.sleep(1)
        try:
            await page.click("button:has-text('SEARCH')", timeout=5000)
        except Exception:
            print("SEARCH click failed")
        await asyncio.sleep(5)

        print(f"API calls captured: {len(api_calls)}")
        for c in api_calls:
            print(f"  URL: {c['url']}")
            print(f"  Method: {c['method']}")
            print(f"  Post: {c['post_data'][:300] if c['post_data'] else 'None'}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(check())
