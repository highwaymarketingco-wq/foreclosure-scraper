"""Debug: Use Gemini Vision to solve reCAPTCHA visual challenge.

Instead of audio (which Google blocks for automated browsers), click the
reCAPTCHA checkbox, take a screenshot of the visual challenge, and send
it to Gemini Vision API to identify which tiles to click.
"""
import asyncio
import base64
import json
import os
import re
import httpx
from patchright.async_api import async_playwright

# Gemini API keys (rotate through them)
GEMINI_KEYS = [
    os.environ.get("GEMINI_API_KEY_1", ""),
    os.environ.get("GEMINI_API_KEY_2", ""),
    os.environ.get("GEMINI_API_KEY_3", ""),
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]
_key_idx = 0

LEXINGTON_URL = "https://www.lex-co.com/Departments/ProbateCourt/ProbateCourtRecordsSearch.aspx"


def _get_key():
    global _key_idx
    if not GEMINI_KEYS:
        return ""
    k = GEMINI_KEYS[_key_idx % len(GEMINI_KEYS)]
    _key_idx += 1
    return k


async def solve_recaptcha_vision(page, challenge_frame):
    """Take screenshot of challenge, send to Gemini Vision, click tiles."""
    # Take screenshot of the challenge frame
    screenshot_bytes = await challenge_frame.screenshot()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

    # Get the challenge prompt (e.g., "Select all images with crosswalks")
    try:
        prompt_text = await challenge_frame.evaluate("""() => {
            // Try to find the challenge prompt text
            const els = document.querySelectorAll('strong, .rc-imageselect-desc-no-canonical, .rc-imageselect-desc');
            for (const el of els) {
                if (el.textContent && el.textContent.trim()) return el.textContent.trim();
            }
            return document.body ? document.body.innerText.substring(0, 200) : '';
        }""")
    except BaseException:
        prompt_text = ""

    print(f"Challenge prompt: {prompt_text}")

    # Send to Gemini Vision
    key = _get_key()
    if not key:
        print("NO GEMINI KEY available")
        return False

    # Use Gemini 2.0 Flash for vision
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"

    # The reCAPTCHA challenge is typically a 3x3 grid of images
    # We need Gemini to tell us which tiles (0-8, left-to-right, top-to-bottom) match
    instruction = f"""Look at this reCAPTCHA image challenge. The prompt is: "{prompt_text}"

This is a 3x3 grid of images (tiles numbered 0-8, left-to-right, top-to-bottom):
0 1 2
3 4 5
6 7 8

Which tile numbers contain images that match the prompt? Return ONLY a JSON array of tile numbers, like [0, 3, 6]. If no tiles match, return []."""

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
            # Extract tile numbers
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
            # reCAPTCHA tiles are typically in table cells
            clicked = await challenge_frame.evaluate(f"""(idx) => {{
                const cells = document.querySelectorAll('.rc-imageselect-tiletarget, td.rc-imageselect-tile');
                if (cells[idx]) {{
                    cells[idx].click();
                    return true;
                }}
                // Try alternate selectors
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
        await asyncio.sleep(5)

        # Take initial screenshot
        await page.screenshot(path="/tmp/lexington_initial.png")
        print("Initial screenshot saved")

        # Find reCAPTCHA iframe
        recaptcha_frame = None
        for frame in page.frames:
            if "recaptcha" in frame.url.lower() or "google.com/recaptcha" in frame.url.lower():
                recaptcha_frame = frame
                print(f"Found reCAPTCHA frame: {frame.url[:100]}")
                break

        if not recaptcha_frame:
            # Try to find by selector
            try:
                recaptcha_element = page.frame_locator("iframe[title*='reCAPTCHA'], iframe[src*='recaptcha']")
                # Click the checkbox
                await recaptcha_element.locator(".recaptcha-checkbox-border").click()
                print("Clicked reCAPTCHA checkbox")
            except BaseException as e:
                print(f"Checkbox click error: {e}")
        else:
            # Click checkbox in the frame
            try:
                await recaptcha_frame.click(".recaptcha-checkbox-border")
                print("Clicked reCAPTCHA checkbox")
            except BaseException as e:
                print(f"Checkbox click error: {e}")

        # Wait for challenge to appear
        await asyncio.sleep(5)

        # Find the challenge frame (different from checkbox frame)
        challenge_frame = None
        for frame in page.frames:
            url = frame.url.lower()
            if "bframe" in url or "recaptcha/api2/bframe" in url:
                challenge_frame = frame
                print(f"Found challenge frame: {frame.url[:100]}")
                break

        if not challenge_frame:
            print("No challenge frame found. Checking all frames:")
            for frame in page.frames:
                print(f"  Frame: {frame.url[:120]}")
            await page.screenshot(path="/tmp/lexington_no_challenge.png")
            await browser.close()
            return

        # Take screenshot of challenge
        await asyncio.sleep(3)
        try:
            await challenge_frame.screenshot(path="/tmp/lexington_challenge.png")
            print("Challenge screenshot saved")
        except BaseException as e:
            print(f"Screenshot error: {e}")

        # Get challenge frame HTML to see what's there
        try:
            html = await challenge_frame.evaluate("() => document.body ? document.body.innerHTML.substring(0, 500) : 'no body'")
            print(f"Challenge frame HTML (first 500): {html[:500]}")
        except BaseException as e:
            print(f"HTML check error: {e}")

        # Try to solve with Gemini Vision
        tiles = await solve_recaptcha_vision(page, challenge_frame)
        if tiles:
            await click_tiles(challenge_frame, tiles)
            await asyncio.sleep(3)
            # Check if solved
            print("Checking if reCAPTCHA is solved...")
            try:
                for frame in page.frames:
                    if "recaptcha" in frame.url.lower() and "api2/anchor" in frame.url.lower():
                        checked = await frame.evaluate("() => document.querySelector('.recaptcha-checkbox-checked') !== null")
                        print(f"reCAPTCHA checked: {checked}")
                        break
            except BaseException as e:
                print(f"Check error: {e}")
        else:
            print("Gemini Vision could not identify tiles")

        # Final screenshot
        await page.screenshot(path="/tmp/lexington_final.png")
        print("Final screenshot saved")
        await browser.close()


asyncio.run(main())
