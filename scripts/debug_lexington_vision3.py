"""Debug: Lexington reCAPTCHA with Gemini Vision v3.

v2 showed the visual challenge DOES load with patchright + Xvfb.
But reCAPTCHA didn't auto-solve — we need Gemini Vision to identify tiles.
The recaptcha-token hidden field is NOT the same as g-recaptcha-response
(which is empty until solved).

Flow:
1. Load page with patchright + non-headless (Xvfb)
2. Click reCAPTCHA checkbox → visual challenge appears
3. Screenshot the challenge
4. Send to Gemini Vision → get tile numbers
5. Click tiles + verify
6. Check g-recaptcha-response for actual token
"""
import asyncio
import base64
import json
import os
import re
import httpx
from patchright.async_api import async_playwright

GEMINI_KEYS = [
    os.environ.get("GEMINI_API_KEY_1", ""),
    os.environ.get("GEMINI_API_KEY_2", ""),
    os.environ.get("GEMINI_API_KEY_3", ""),
    os.environ.get("GEMINI_API_KEY_4", ""),
    os.environ.get("GEMINI_API_KEY_5", ""),
    os.environ.get("GEMINI_API_KEY_6", ""),
    os.environ.get("GEMINI_API_KEY_7", ""),
    os.environ.get("GEMINI_API_KEY_8", ""),
    os.environ.get("GEMINI_API_KEY_9", ""),
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]
_key_idx = 0

LEXINGTON_URL = "https://www.lex-co.com/ProbateSearch/estates"


def _get_key():
    global _key_idx
    if not GEMINI_KEYS:
        return ""
    k = GEMINI_KEYS[_key_idx % len(GEMINI_KEYS)]
    _key_idx += 1
    return k


async def get_recaptcha_response(page):
    """Get the actual g-recaptcha-response value (empty until solved)."""
    try:
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                resp = await frame.evaluate("""() => {
                    const el = document.querySelector('#g-recaptcha-response');
                    return el ? el.value : null;
                }""")
                if resp:
                    return resp
        # Also try textarea
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                resp = await frame.evaluate("""() => {
                    const el = document.querySelector('textarea[name="g-recaptcha-response"]');
                    return el ? el.value : null;
                }""")
                if resp:
                    return resp
    except BaseException as e:
        print(f"get_recaptcha_response error: {e}")
    return None


async def solve_with_gemini(page, challenge_frame, attempt=0):
    """Take screenshot, send to Gemini, click tiles, verify."""
    # Get the challenge prompt
    try:
        prompt_text = await challenge_frame.evaluate("""() => {
            const els = document.querySelectorAll('.rc-imageselect-desc-no-canonical, .rc-imageselect-desc, strong');
            for (const el of els) {
                if (el.textContent && el.textContent.trim()) return el.textContent.trim();
            }
            return '';
        }""")
    except BaseException:
        prompt_text = ""
    print(f"  Challenge prompt: {prompt_text}")

    # Take screenshot of page (includes challenge overlay)
    screenshot_bytes = await page.screenshot()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

    # Send to Gemini Vision
    key = _get_key()
    if not key:
        print("  NO GEMINI KEY available")
        return False

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"

    instruction = f"""Look at this screenshot of a reCAPTCHA challenge. The prompt text says: "{prompt_text}"

The reCAPTCHA challenge is a 3x3 grid of images. The tiles are numbered 0-8:
0 1 2
3 4 5
6 7 8

Which tile numbers contain images that match what the prompt asks for? Return ONLY a JSON array of tile numbers. Example: [0, 3, 6]
If no tiles match, return []. If you can't see the grid, return []."""

    payload = {
        "contents": [{
            "parts": [
                {"text": instruction},
                {"inline_data": {"mime_type": "image/png", "data": screenshot_b64}}
            ]
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100}
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                print(f"  Gemini API error: {resp.status_code} {resp.text[:200]}")
                return False
            data = resp.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            print(f"  Gemini response: {text}")
            match = re.search(r'\[([0-9,\s]*)\]', text)
            if match:
                tiles = [int(t.strip()) for t in match.group(1).split(",") if t.strip()]
                print(f"  Tiles to click: {tiles}")
                if not tiles:
                    print("  No tiles to click — skip verification")
                    return False
                # Click tiles
                for tile_idx in tiles:
                    try:
                        clicked = await challenge_frame.evaluate(f"""(idx) => {{
                            const cells = document.querySelectorAll('td.rc-imageselect-tile, .rc-imageselect-tiletarget, .rc-imageselect-tile');
                            if (cells[idx]) {{ cells[idx].click(); return true; }}
                            return false;
                        }}""", tile_idx)
                        print(f"    Tile {tile_idx}: clicked={clicked}")
                        await asyncio.sleep(0.3)
                    except BaseException as e:
                        print(f"    Tile {tile_idx}: error={e}")

                await asyncio.sleep(1)

                # Click verify button
                try:
                    await challenge_frame.evaluate("""() => {
                        const btn = document.getElementById('recaptcha-verify-button') || document.querySelector('.rc-button-default');
                        if (btn) btn.click();
                    }""")
                    print("  Verify button clicked")
                except BaseException as e:
                    print(f"  Verify button error: {e}")

                return True
    except BaseException as e:
        print(f"  Gemini error: {e}")
        return False

    return False


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        print("Loading Lexington probate page...")
        await page.goto(LEXINGTON_URL, timeout=60000)
        await asyncio.sleep(10)

        # Find reCAPTCHA anchor frame (checkbox)
        recaptcha_frame = None
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                recaptcha_frame = frame
                break

        if not recaptcha_frame:
            print("No reCAPTCHA frame found!")
            await page.screenshot(path="/tmp/lex_v3_noframe.png")
            await browser.close()
            return

        print("Found reCAPTCHA anchor frame")

        # Click the checkbox
        try:
            await recaptcha_frame.click(".recaptcha-checkbox-border")
            print("Clicked reCAPTCHA checkbox")
        except BaseException as e:
            print(f"Checkbox click error: {e}")

        # Wait for challenge to appear
        await asyncio.sleep(5)

        # Find the challenge frame
        challenge_frame = None
        for frame in page.frames:
            if "recaptcha/api2/bframe" in frame.url:
                challenge_frame = frame
                break

        if not challenge_frame:
            print("No challenge frame found")
            # Maybe reCAPTCHA auto-solved (non-interactive mode)
            resp = await get_recaptcha_response(page)
            if resp:
                print(f"reCAPTCHA auto-solved! Token: {resp[:60]}...")
            await browser.close()
            return

        print("Found challenge frame")

        # Wait for challenge to fully load
        await asyncio.sleep(3)

        # Check if visual challenge loaded
        try:
            img_count = await challenge_frame.evaluate("() => document.querySelectorAll('img').length")
            print(f"Images in challenge frame: {img_count}")
        except BaseException as e:
            print(f"Image count error: {e}")

        # Try to solve with Gemini Vision (up to 3 attempts)
        for attempt in range(3):
            print(f"\n--- Gemini Vision attempt {attempt + 1} ---")
            solved = await solve_with_gemini(page, challenge_frame, attempt)
            if solved:
                await asyncio.sleep(5)

                # Check if reCAPTCHA is actually solved
                resp = await get_recaptcha_response(page)
                if resp:
                    print(f"\n*** RECAPTCHA SOLVED! ***")
                    print(f"g-recaptcha-response: {resp[:60]}...")

                    # Now try to perform the search
                    print("\nPerforming estate search...")
                    # Fill search form
                    try:
                        # Look for search input
                        search_input = await page.query_selector("input[type='text'], input[name*='name'], input[name*='Name']")
                        if search_input:
                            await search_input.fill("Smith")
                            print("Search filled with 'Smith'")

                        # Click search button
                        search_btn = await page.query_selector("input[type='submit'], button[type='submit'], .search-btn, .btn")
                        if search_btn:
                            await search_btn.click()
                            print("Search button clicked")
                            await asyncio.sleep(10)

                            # Get page content
                            content = await page.content()
                            print(f"Page content length: {len(content)}")

                            # Check for results
                            if "estate" in content.lower() or "case" in content.lower():
                                print("Results appear to be on page!")
                                # Save page HTML
                                with open("/tmp/lex_search_results.html", "w") as f:
                                    f.write(content)
                                print("Results saved to /tmp/lex_search_results.html")
                        else:
                            print("No search button found")
                    except BaseException as e:
                        print(f"Search error: {e}")

                    break
                else:
                    print("  reCAPTCHA not solved yet, trying again...")

                    # Check for new challenge (may have new images)
                    try:
                        img_count = await challenge_frame.evaluate("() => document.querySelectorAll('img').length")
                        print(f"  Images now: {img_count}")
                    except BaseException:
                        pass
            else:
                # Reload challenge
                try:
                    await challenge_frame.evaluate("""() => {
                        const btn = document.getElementById('recaptcha-reload-button') || document.querySelector('.rc-button-reload');
                        if (btn) btn.click();
                    }""")
                    print("  Reloaded challenge")
                    await asyncio.sleep(3)
                except BaseException:
                    pass

        # Final screenshot
        await page.screenshot(path="/tmp/lex_v3_final.png")
        print("\nFinal screenshot saved")
        await browser.close()


asyncio.run(main())
