"""Debug: Lexington reCAPTCHA with Gemini Vision v2.

v1 found that reCAPTCHA loads and checkbox clicks work, but Frame.screenshot()
doesn't exist. Use page.screenshot() or element_handle.screenshot() instead.
Also check if reCAPTCHA auto-solved (token was present in frame HTML).
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


async def solve_recaptcha_vision(page, challenge_frame):
    """Take screenshot of challenge, send to Gemini Vision, click tiles."""
    # Check if reCAPTCHA already auto-solved
    try:
        token = await challenge_frame.evaluate("() => { const el = document.querySelector('#recaptcha-token'); return el ? el.value : null; }")
        if token and len(token) > 20:
            print(f"reCAPTCHA already has token: {token[:60]}...")
            return "auto_solved"
    except BaseException as e:
        print(f"Token check error: {e}")

    # Take screenshot of the whole page (challenge frame is visible as overlay)
    screenshot_bytes = await page.screenshot()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

    # Get the challenge prompt
    try:
        prompt_text = await challenge_frame.evaluate("""() => {
            const els = document.querySelectorAll('strong, .rc-imageselect-desc-no-canonical, .rc-imageselect-desc');
            for (const el of els) {
                if (el.textContent && el.textContent.trim()) return el.textContent.trim();
            }
            return document.body ? document.body.innerText.substring(0, 300) : '';
        }""")
    except BaseException:
        prompt_text = ""

    print(f"Challenge prompt: {prompt_text}")

    # Check if challenge is actually visible (not just skeleton)
    try:
        body_text = await challenge_frame.evaluate("() => document.body ? document.body.innerText.substring(0, 500) : ''")
        print(f"Challenge body text: {body_text[:200]}")
    except BaseException as e:
        print(f"Body text error: {e}")

    # Get all images in the challenge frame
    try:
        images = await challenge_frame.evaluate("""() => {
            const imgs = document.querySelectorAll('img.rc-imageselect-tile, img');
            return Array.from(imgs).map(img => ({
                src: img.src ? img.src.substring(0, 100) : 'no-src',
                class: img.className,
                width: img.width,
                height: img.height,
            }));
        }""")
        print(f"Images in challenge frame: {len(images)}")
        for img in images[:5]:
            print(f"  {img}")
    except BaseException as e:
        print(f"Image check error: {e}")

    # Send to Gemini Vision
    key = _get_key()
    if not key:
        print("NO GEMINI KEY available")
        return False

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"

    instruction = f"""Look at this screenshot of a reCAPTCHA challenge. The prompt is: "{prompt_text}"

The reCAPTCHA challenge is typically a 3x3 grid of images (tiles numbered 0-8, left-to-right, top-to-bottom):
0 1 2
3 4 5
6 7 8

Which tile numbers contain images that match the prompt? Return ONLY a JSON array of tile numbers, like [0, 3, 6]. If no tiles match or you can't see the challenge, return []."""

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
                print(f"Gemini API error: {resp.status_code} {resp.text[:200]}")
                return False
            data = resp.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            print(f"Gemini response: {text}")
            match = re.search(r'\[([0-9,\s]*)\]', text)
            if match:
                tiles = [int(t.strip()) for t in match.group(1).split(",") if t.strip()]
                print(f"Tiles to click: {tiles}")
                return tiles
    except BaseException as e:
        print(f"Gemini error: {e}")
        return False

    return False


async def click_tiles(challenge_frame, tiles):
    """Click the specified tiles in the 3x3 grid."""
    for tile_idx in tiles:
        try:
            clicked = await challenge_frame.evaluate(f"""(idx) => {{
                const cells = document.querySelectorAll('.rc-imageselect-tiletarget, td.rc-imageselect-tile');
                if (cells[idx]) {{
                    cells[idx].click();
                    return true;
                }}
                const tiles = document.querySelectorAll('[role="button"], .rc-imageselect-tile');
                if (tiles[idx]) {{
                    tiles[idx].click();
                    return true;
                }}
                return false;
            }}""", tile_idx)
            print(f"  Tile {tile_idx}: clicked={clicked}")
            await asyncio.sleep(0.5)
        except BaseException as e:
            print(f"  Tile {tile_idx}: error={e}")

    # Click verify button
    try:
        await challenge_frame.evaluate("""() => {
            const btn = document.querySelector('#recaptcha-verify-button, .rc-button-default');
            if (btn) btn.click();
        }""")
        print("Verify button clicked")
    except BaseException as e:
        print(f"Verify button error: {e}")


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

        # List all frames
        print("Frames after page load:")
        for frame in page.frames:
            print(f"  {frame.url[:120]}")

        # Find reCAPTCHA anchor frame (checkbox)
        recaptcha_frame = None
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                recaptcha_frame = frame
                print(f"Found reCAPTCHA anchor frame")
                break

        if recaptcha_frame:
            try:
                await recaptcha_frame.click(".recaptcha-checkbox-border")
                print("Clicked reCAPTCHA checkbox")
            except BaseException as e:
                print(f"Checkbox click error: {e}")
        else:
            # Try frame_locator approach
            try:
                recaptcha_fl = page.frame_locator("iframe[src*='recaptcha/api2/anchor']")
                await recaptcha_fl.locator(".recaptcha-checkbox-border").click()
                print("Clicked reCAPTCHA checkbox via frame_locator")
            except BaseException as e:
                print(f"frame_locator click error: {e}")

        # Wait for challenge to appear
        await asyncio.sleep(5)

        # Find the challenge frame (bframe)
        challenge_frame = None
        for frame in page.frames:
            if "recaptcha/api2/bframe" in frame.url:
                challenge_frame = frame
                print(f"Found challenge frame")
                break

        if not challenge_frame:
            print("No challenge frame found.")
            await page.screenshot(path="/tmp/lex_v2_no_challenge.png")
            await browser.close()
            return

        # Wait for challenge to fully load
        await asyncio.sleep(5)

        # Check challenge frame content
        try:
            html = await challenge_frame.evaluate("() => document.body ? document.body.innerHTML.substring(0, 1000) : 'no body'")
            print(f"Challenge frame HTML (first 1000): {html[:500]}")
        except BaseException as e:
            print(f"HTML check error: {e}")

        # Check for images (visual challenge vs skeleton)
        try:
            img_count = await challenge_frame.evaluate("() => document.querySelectorAll('img').length")
            print(f"Images in challenge frame: {img_count}")
        except BaseException as e:
            print(f"Image count error: {e}")

        # Take screenshot of page (includes challenge overlay)
        await page.screenshot(path="/tmp/lex_v2_challenge.png")
        print("Page screenshot saved")

        # Try to solve with Gemini Vision
        tiles = await solve_recaptcha_vision(page, challenge_frame)
        if tiles == "auto_solved":
            print("reCAPTCHA auto-solved! Proceeding with search...")
            # Try to perform search
        elif tiles:
            await click_tiles(challenge_frame, tiles)
            await asyncio.sleep(3)
            # Check if solved
            print("Checking if reCAPTCHA is solved...")
            try:
                for frame in page.frames:
                    if "recaptcha/api2/anchor" in frame.url:
                        checked = await frame.evaluate("() => document.querySelector('.recaptcha-checkbox-checked') !== null")
                        print(f"reCAPTCHA checked: {checked}")
                        break
            except BaseException as e:
                print(f"Check error: {e}")
        else:
            print("Gemini Vision could not identify tiles")

        # Final screenshot
        await page.screenshot(path="/tmp/lex_v2_final.png")
        print("Final screenshot saved")
        await browser.close()


asyncio.run(main())
