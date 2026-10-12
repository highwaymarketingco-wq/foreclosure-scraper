"""Debug: Use Cloudflare Turnstile sitekey to solve challenge directly.

The Turnstile sitekey is: 0x4AAAAAAAhrAOTfac6OZIll
We can create a minimal HTML page with the Turnstile widget, load it in
patchright, wait for auto-solve, then use the token with the NCCash API.
"""
import asyncio
import httpx
from patchright.async_api import async_playwright

SITEKEY = "0x4AAAAAAAhrAOTfac6OZIll"
# The page URL that the Turnstile is normally embedded on
PAGE_URL = "https://unclaimed.nccash.gov/app/claim-search"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        # Navigate to the real page first (so origin matches)
        await page.goto(PAGE_URL, timeout=60000)
        await asyncio.sleep(10)

        # Inject our own Turnstile widget with the known sitekey
        await page.evaluate(f"""() => {{
            // Remove existing widgets
            document.querySelectorAll('[id^="cf-chl-widget"]').forEach(e => e.remove());
            
            // Create a new container
            const container = document.createElement('div');
            container.id = 'my-turnstile';
            document.body.appendChild(container);
            
            // Load Turnstile JS if not already loaded
            if (!window.turnstile) {{
                const script = document.createElement('script');
                script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
                script.async = true;
                script.defer = true;
                document.head.appendChild(script);
            }}
        }}""")

        # Wait for Turnstile JS to load
        await asyncio.sleep(5)

        # Explicitly render the widget
        await page.evaluate(f"""() => {{
            if (window.turnstile) {{
                window.turnstile.render('#my-turnstile', {{
                    sitekey: '{SITEKEY}',
                    callback: function(token) {{
                        window.__turnstile_token = token;
                    }},
                }});
            }}
        }}""")

        # Wait for token
        token = None
        for i in range(30):
            await asyncio.sleep(2)
            token = await page.evaluate("""() => {
                if (window.__turnstile_token) return window.__turnstile_token;
                try {
                    let t = turnstile.getResponse();
                    if (t && t.length > 10) return t;
                } catch(e) {}
                return null;
            }""")
            if token:
                print(f"GOT TOKEN at {i*2}s: {token[:60]}...")
                break
            if i % 5 == 0:
                widget_html = await page.evaluate("""() => {
                    const w = document.querySelector('#my-turnstile');
                    return w ? w.innerHTML.substring(0, 200) : 'no widget';
                }""")
                print(f"  {i*2}s: no token, widget: {widget_html[:100]}")

        if not token:
            print("NO TOKEN after 60s")
            # Dump page content for debugging
            title = await page.title()
            print(f"Page title: {title}")
            await browser.close()
            return

        # Try to use the token with the API
        print(f"\nUsing token to search API...")
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
