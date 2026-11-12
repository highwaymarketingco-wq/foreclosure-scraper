"""Debug Turnstile v6: try frame_locator to click inside CF iframe."""
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
        await asyncio.sleep(10)

        # Get the sitekey
        sitekey = await page.evaluate("""() => {
            const w = document.querySelector('[data-sitekey]');
            return w ? w.getAttribute('data-sitekey') : null;
        }""")
        print(f"Sitekey: {sitekey}")

        # Get widget info
        widget_info = await page.evaluate("""() => {
            const widgets = document.querySelectorAll('[id^="cf-chl-widget"]');
            return Array.from(widgets).map(w => ({
                id: w.id,
                sitekey: w.getAttribute('data-sitekey'),
                innerHTML: w.innerHTML.substring(0, 200),
            }));
        }""")
        print(f"Widgets: {widget_info}")

        # Try to find and click the checkbox inside Turnstile iframe
        # Method 1: frame_locator
        try:
            fl = page.frame_locator("iframe[src*='challenges.cloudflare']")
            # Try clicking the checkbox
            await fl.locator("input[type='checkbox']").click(timeout=5000)
            print("Clicked checkbox via frame_locator!")
        except Exception as e:
            print(f"frame_locator checkbox failed: {e}")

        # Method 2: Find the iframe bounding box and click
        try:
            iframe_info = await page.evaluate("""() => {
                const iframes = document.querySelectorAll("iframe[src*='challenges.cloudflare']");
                if (iframes.length === 0) return null;
                const r = iframes[0].getBoundingClientRect();
                return {x: r.x, y: r.y, w: r.width, h: r.height};
            }""")
            if iframe_info:
                print(f"Iframe bbox: {iframe_info}")
                # Click at the checkbox position (left side of widget)
                click_x = iframe_info["x"] + 28
                click_y = iframe_info["y"] + iframe_info["h"] / 2
                print(f"Clicking at ({click_x}, {click_y})")
                await page.mouse.move(click_x - 50, click_y - 50)
                await asyncio.sleep(0.5)
                await page.mouse.move(click_x, click_y)
                await asyncio.sleep(0.3)
                await page.mouse.click(click_x, click_y)
                print("Clicked!")
                await asyncio.sleep(10)

                token = await page.evaluate("""() => {
                    try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                    const el = document.querySelector('[name="cf-turnstile-response"]');
                    if (el && el.value && el.value.length > 10) return el.value;
                    return null;
                }""")
                print(f"Token after click: {token}")
        except Exception as e:
            print(f"Bbox click failed: {e}")

        # Method 3: Try to use turnstile.reset() then wait
        try:
            await page.evaluate("turnstile.reset()")
            print("Reset Turnstile")
            for i in range(15):
                await asyncio.sleep(2)
                token = await page.evaluate("""() => {
                    try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                    return null;
                }""")
                if token:
                    print(f"Token after reset at {i*2}s: {token[:50]}...")
                    break
            else:
                print("No token after reset + 30s wait")
        except Exception as e:
            print(f"Reset failed: {e}")

        await browser.close()


asyncio.run(main())
