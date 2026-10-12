"""Debug: Turnstile v11 - use page.evaluate to inject script (bypass CSP).

v10 failed because add_script_tag was blocked by CSP. Use page.evaluate
to create a script element programmatically, which may bypass CSP.
Also try loading a data: URL with minimal Turnstile HTML.
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

        # Navigate to the real page (origin must match for Turnstile)
        print("Loading real page...")
        await page.goto(PAGE_URL, timeout=60000)
        await asyncio.sleep(8)

        # Check if turnstile is already loaded from the Angular app
        ts_available = await page.evaluate("() => typeof window.turnstile !== 'undefined'")
        print(f"turnstile already loaded: {ts_available}")

        if not ts_available:
            # Use evaluate to create script element (bypasses CSP)
            print("Injecting Turnstile JS via evaluate...")
            loaded = await page.evaluate("""async () => {
                return new Promise((resolve) => {
                    if (window.turnstile) { resolve(true); return; }
                    const script = document.createElement('script');
                    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
                    script.async = true;
                    script.onload = () => resolve(true);
                    script.onerror = (e) => resolve(false);
                    document.head.appendChild(script);
                    // Also try the explicit render version
                    const script2 = document.createElement('script');
                    script2.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
                    script2.async = true;
                    document.head.appendChild(script2);
                    // Wait up to 15s
                    let count = 0;
                    const interval = setInterval(() => {
                        count++;
                        if (window.turnstile || count > 15) {
                            clearInterval(interval);
                            resolve(!!window.turnstile);
                        }
                    }, 1000);
                });
            }""")
            print(f"Turnstile JS loaded: {loaded}")

            if not loaded:
                # Try alternative: navigate to the page and wait longer
                # The Angular app may load it after rendering
                print("Waiting for Angular to load Turnstile...")
                for i in range(20):
                    await asyncio.sleep(2)
                    ts_available = await page.evaluate("() => typeof window.turnstile !== 'undefined'")
                    if ts_available:
                        print(f"Turnstile loaded after {(i+1)*2}s")
                        break
                else:
                    print("Turnstile JS never loaded. Trying to intercept API calls...")
                    # Check if Turnstile is loaded via the Angular config
                    config = await page.evaluate("""async () => {
                        try {
                            const resp = await fetch('https://unclaimed.nccash.gov/SWS/app/properties');
                            return await resp.json();
                        } catch(e) { return {error: e.message}; }
                    }""")
                    print(f"Config: {config}")

                    # Try to find Turnstile sitekey in page source
                    page_html = await page.content()
                    if 'turnstile' in page_html.lower():
                        print("Turnstile found in page HTML!")
                    if 'cf-turnstile' in page_html.lower():
                        print("cf-turnstile class found in page HTML!")
                    if 'challenges.cloudflare' in page_html.lower():
                        print("challenges.cloudflare found in page HTML!")

                    # Try to trigger the Angular search to load Turnstile
                    print("Trying to trigger Angular search...")
                    try:
                        # Look for search button
                        btn = await page.query_selector("button[type='submit'], .search-btn, .btn-search")
                        if btn:
                            await btn.click()
                            print("Search button clicked")
                            await asyncio.sleep(10)
                            ts_available = await page.evaluate("() => typeof window.turnstile !== 'undefined'")
                            print(f"Turnstile after search: {ts_available}")
                    except BaseException as e:
                        print(f"Search trigger error: {e}")

                    if not ts_available:
                        await browser.close()
                        return

        # Now render the widget
        print("Rendering Turnstile widget...")
        render_result = await page.evaluate(f"""() => {{
            // Remove existing widgets
            document.querySelectorAll('[id^="cf-chl-widget"]').forEach(e => e.remove());

            // Create container
            const container = document.createElement('div');
            container.id = 'ts-container';
            container.style.position = 'fixed';
            container.style.top = '100px';
            container.style.left = '50%';
            container.style.transform = 'translateX(-50%)';
            container.style.zIndex = '99999';
            document.body.appendChild(container);

            try {{
                const widgetId = window.turnstile.render('#ts-container', {{
                    sitekey: '{SITEKEY}',
                    callback: function(token) {{
                        window.__ts_token = token;
                    }},
                    'error-callback': function(err) {{
                        window.__ts_error = JSON.stringify(err);
                    }},
                    'timeout-callback': function() {{
                        window.__ts_timeout = true;
                    }},
                }});
                return {{success: true, widgetId: widgetId}};
            }} catch(e) {{
                return {{success: false, error: e.message}};
            }}
        }}""")
        print(f"Render result: {render_result}")

        if not render_result or not render_result.get('success'):
            print(f"Render failed: {render_result}")
            await browser.close()
            return

        # Wait for token
        token = None
        for i in range(45):
            await asyncio.sleep(2)
            result = await page.evaluate("""() => ({
                token: window.__ts_token || null,
                error: window.__ts_error || null,
                timeout: window.__ts_timeout || false,
                widgetHTML: document.querySelector('#ts-container')?.innerHTML?.substring(0, 300) || 'no container',
                widgetLen: document.querySelector('#ts-container')?.innerHTML?.length || 0,
                iframes: document.querySelectorAll('iframe').length,
                response: (() => { try { return turnstile.getResponse(); } catch(e) { return 'err: ' + e.message; } })(),
            })""")

            if result.get('token'):
                token = result['token']
                print(f"\nGOT TOKEN at {i*2}s: {token[:60]}...")
                break

            if result.get('error'):
                print(f"  {i*2}s: ERROR: {result['error']}")

            if i % 5 == 0:
                print(f"  {i*2}s: no token, widget_len={result.get('widgetLen')}, iframes={result.get('iframes')}, response={str(result.get('response'))[:50]}")

        if not token:
            print("\nNO TOKEN after 90s")
            await page.screenshot(path="/tmp/ts11_final.png")
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
