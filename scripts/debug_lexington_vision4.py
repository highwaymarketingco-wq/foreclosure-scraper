"""Debug: Lexington reCAPTCHA with Gemini Vision v4.

v3 showed challenge loads (16 images = 4x4 grid), but gemini-3.8-flash
returns 503 (overloaded). Fix: try multiple models + keys with retries.
Also handle 4x4 grids (not just 3x3).
"""
import asyncio
import base64
import json
import os
import re
import httpx
from patchright.async_api import async_playwright

GEMINI_KEYS = [os.environ.get(f"GEMINI_API_KEY_{i}", "") for i in range(1, 10)]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
]
_key_idx = 0
_model_idx = 0

LEXINGTON_URL = "https://www.lex-co.com/ProbateSearch/estates"


def _get_key():
    global _key_idx
    k = GEMINI_KEYS[_key_idx % len(GEMINI_KEYS)]
    _key_idx += 1
    return k


def _get_model():
    global _model_idx
    m = GEMINI_MODELS[_model_idx % len(GEMINI_MODELS)]
    _model_idx += 1
    return m


async def get_recaptcha_response(page):
    """Get the actual g-recaptcha-response value."""
    try:
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                resp = await frame.evaluate("""() => {
                    const el = document.querySelector('#g-recaptcha-response')
                        || document.querySelector('textarea[name="g-recaptcha-response"]');
                    return el ? el.value : null;
                }""")
                if resp and len(resp) > 20:
                    return resp
    except BaseException:
        pass
    return None


async def solve_with_gemini(page, challenge_frame, attempt=0):
    """Screenshot → Gemini Vision → click tiles → verify."""
    # Get challenge prompt
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

    # Get grid dimensions
    try:
        grid_info = await challenge_frame.evaluate("""() => {
            const rows = document.querySelectorAll('.rc-imageselect-table tr');
            const cols = rows.length > 0 ? rows[0].querySelectorAll('td').length : 0;
            const tiles = document.querySelectorAll('td.rc-imageselect-tile, .rc-imageselect-tiletarget');
            return {rows: rows.length, cols: cols, total: tiles.length};
        }""")
        print(f"  Grid: {grid_info}")
    except BaseException as e:
        grid_info = {"rows": 3, "cols": 3, "total": 9}
        print(f"  Grid detection error: {e}, assuming 3x3")

    # Take full page screenshot
    screenshot_bytes = await page.screenshot()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

    # Try each model + key combination
    for model_idx in range(len(GEMINI_MODELS)):
        model = _get_model()
        for key_idx in range(len(GEMINI_KEYS)):
            key = _get_key()
            if not key:
                continue

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

            grid_desc = f"{grid_info['rows']}x{grid_info['cols']}" if grid_info.get('rows') else "3x3"
            total_tiles = grid_info.get('total', 9)

            instruction = f"""Look at this screenshot of a reCAPTCHA challenge. The prompt text says: "{prompt_text}"

The reCAPTCHA challenge is a {grid_desc} grid of images. The tiles are numbered 0 to {total_tiles-1}:
""" + "\n".join(
                " ".join(str(r * grid_info.get('cols', 3) + c) for c in range(grid_info.get('cols', 3)))
                for r in range(grid_info.get('rows', 3))
            ) + f"""

Which tile numbers contain images that match what the prompt asks for? Return ONLY a JSON array of tile numbers. Example: [0, 3, 6]
If no tiles match, return []. If you can't see the grid clearly, return []."""

            payload = {
                "contents": [{
                    "parts": [
                        {"text": instruction},
                        {"inline_data": {"mime_type": "image/png", "data": screenshot_b64}}
                    ]
                }],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500}
            }

            try:
                async with httpx.AsyncClient(timeout=45) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 503:
                        print(f"  {model} key{key_idx}: 503 overloaded, trying next...")
                        continue
                    if resp.status_code == 429:
                        print(f"  {model} key{key_idx}: 429 rate limited, trying next...")
                        continue
                    if resp.status_code != 200:
                        print(f"  {model} key{key_idx}: {resp.status_code}")
                        continue
                    data = resp.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    print(f"  {model} response: {text}")

                    # Try to extract JSON array from response
                    text = text.strip()
                    text = re.sub(r'^```(?:json)?\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                    text = text.strip()

                    tiles = []
                    match = re.search(r'\[([0-9,\s]*)\]', text)
                    if match:
                        tile_strs = [t.strip() for t in match.group(1).split(",") if t.strip()]
                        tiles = [int(t) for t in tile_strs]
                    else:
                        try:
                            parsed = json.loads(text)
                            if isinstance(parsed, list):
                                tiles = [int(t) for t in parsed]
                        except BaseException:
                            pass

                    print(f"  Tiles to click: {tiles}")

                    if not tiles:
                        try:
                            await challenge_frame.evaluate("""() => {
                                const btn = document.querySelector('.rc-imageselect-skip, .rc-button-skip');
                                if (btn) btn.click();
                            }""")
                            print("  Clicked skip (no matching tiles)")
                        except BaseException:
                            pass
                        return True

                    # Click tiles
                    for tile_idx in tiles:
                        if tile_idx >= total_tiles:
                            continue
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

                    # Click verify
                    try:
                        await challenge_frame.evaluate("""() => {
                            const btn = document.getElementById('recaptcha-verify-button')
                                || document.querySelector('.rc-button-default');
                            if (btn) btn.click();
                        }""")
                        print("  Verify button clicked")
                    except BaseException as e:
                        print(f"  Verify button error: {e}")

                    return True
            except BaseException as e:
                print(f"  {model} error: {e}")
                continue

    print("  All models/keys exhausted")
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

        # Find reCAPTCHA anchor frame
        recaptcha_frame = None
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                recaptcha_frame = frame
                break

        if not recaptcha_frame:
            print("No reCAPTCHA frame found!")
            await page.screenshot(path="/tmp/lex_v4_noframe.png")
            await browser.close()
            return

        print("Found reCAPTCHA anchor frame")

        # Click checkbox
        try:
            await recaptcha_frame.click(".recaptcha-checkbox-border")
            print("Clicked reCAPTCHA checkbox")
        except BaseException as e:
            print(f"Checkbox click error: {e}")

        await asyncio.sleep(5)

        # Find challenge frame
        challenge_frame = None
        for frame in page.frames:
            if "recaptcha/api2/bframe" in frame.url:
                challenge_frame = frame
                break

        if not challenge_frame:
            print("No challenge frame - maybe auto-solved")
            resp = await get_recaptcha_response(page)
            if resp:
                print(f"Auto-solved! Token: {resp[:60]}...")
            await browser.close()
            return

        print("Found challenge frame")
        await asyncio.sleep(3)

        # Try up to 5 solve attempts
        for attempt in range(5):
            print(f"\n--- Attempt {attempt + 1} ---")
            solved = await solve_with_gemini(page, challenge_frame, attempt)
            if solved:
                await asyncio.sleep(5)
                resp = await get_recaptcha_response(page)
                if resp:
                    print(f"\n*** RECAPTCHA SOLVED! ***")
                    print(f"Token: {resp[:60]}...")

                    # Perform search
                    print("\nPerforming estate search...")
                    try:
                        search_input = await page.query_selector("input[type='text'], input[name*='name'], input[name*='Name'], #Name")
                        if search_input:
                            await search_input.fill("Smith")
                            print("Filled 'Smith'")

                        search_btn = await page.query_selector("input[type='submit'], button[type='submit'], .search-btn, .btn, button")
                        if search_btn:
                            await search_btn.click()
                            print("Clicked search")
                            await asyncio.sleep(10)
                            content = await page.content()
                            print(f"Page content: {len(content)} chars")
                            with open("/tmp/lex_search_results.html", "w") as f:
                                f.write(content)
                            print("Results saved")
                    except BaseException as e:
                        print(f"Search error: {e}")
                    break
                else:
                    print("  Not solved yet, reloading...")
                    try:
                        await challenge_frame.evaluate("""() => {
                            const btn = document.getElementById('recaptcha-reload-button')
                                || document.querySelector('.rc-button-reload');
                            if (btn) btn.click();
                        }""")
                    except BaseException:
                        pass
                    await asyncio.sleep(3)
            else:
                print("  Reload challenge...")
                try:
                    await challenge_frame.evaluate("""() => {
                        const btn = document.getElementById('recaptcha-reload-button')
                            || document.querySelector('.rc-button-reload');
                        if (btn) btn.click();
                    }""")
                except BaseException:
                    pass
                await asyncio.sleep(3)

        await page.screenshot(path="/tmp/lex_v4_final.png")
        print("\nFinal screenshot saved")
        await browser.close()


asyncio.run(main())
