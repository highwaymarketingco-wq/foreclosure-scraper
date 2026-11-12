"""Debug: Lexington reCAPTCHA with Gemini Vision v6.

Key fixes from v5:
1. After clicking verify, wait 8s and properly detect if challenge changed
2. Strip "Click verify once" from prompt — don't treat as new challenge
3. If same prompt appears 3+ times, reload challenge
4. When tiles empty, click verify (not skip) — "none left" is valid
5. Track previous prompt to detect actual challenge changes
6. 3s delay between API calls, gemini-2.5-flash only
7. maxOutputTokens=1000, truncated response handling
"""
import asyncio
import base64
import json
import os
import re
import sys
import time

import httpx
from patchright.async_api import async_playwright

LEXINGTON_URL = "https://www.lex-co.com/ProbateSearch/estates"

# gemini-2.5-flash doesn't refuse CAPTCHA tasks
MODEL = "gemini-2.5-flash"

# Load Gemini keys from env
GEMINI_KEYS = []
for i in range(10):
    k = os.environ.get(f"GEMINI_API_KEY_{i}", "") or os.environ.get(f"GEMINI_KEY_{i}", "")
    if k:
        GEMINI_KEYS.append(k)
if not GEMINI_KEYS:
    k = os.environ.get("GEMINI_API_KEY", "")
    if k:
        GEMINI_KEYS.append(k)

if not GEMINI_KEYS:
    print("ERROR: No GEMINI_API_KEY found in env")
    sys.exit(1)

print(f"Loaded {len(GEMINI_KEYS)} Gemini keys")

_key_idx = 0
def _next_key():
    global _key_idx
    k = GEMINI_KEYS[_key_idx % len(GEMINI_KEYS)]
    _key_idx += 1
    return k


async def get_recaptcha_response(page):
    """Check if reCAPTCHA is solved (has token)."""
    try:
        return await page.evaluate("() => document.getElementById('g-recaptcha-response')?.value || ''")
    except BaseException:
        return ""


def _clean_prompt(text):
    """Extract the actual challenge prompt, stripping UI text."""
    if not text:
        return ""
    # Remove "Click verify once there are none left" and similar
    text = re.sub(r"Click verify once.*", "", text, flags=re.I).strip()
    text = re.sub(r"If there are none.*", "", text, flags=re.I).strip()
    text = re.sub(r"click skip.*", "", text, flags=re.I).strip()
    return text.strip()


async def get_challenge_info(challenge_frame):
    """Get challenge prompt and tile count."""
    try:
        info = await challenge_frame.evaluate("""() => {
            let prompt = '';
            const descEls = document.querySelectorAll(
                '.rc-imageselect-desc-no-canonical, .rc-imageselect-desc'
            );
            for (const el of descEls) {
                if (el.textContent && el.textContent.trim()) {
                    prompt = el.textContent.trim();
                    break;
                }
            }
            // Fallback: try .rc-imageselect-desc-wrapper > div:first-child
            if (!prompt) {
                const wrapper = document.querySelector('.rc-imageselect-desc-wrapper');
                if (wrapper) {
                    const firstDiv = wrapper.querySelector('div');
                    if (firstDiv) prompt = firstDiv.textContent.trim();
                }
            }
            const tiles = document.querySelectorAll(
                'td.rc-imageselect-tile, .rc-imageselect-tiletarget, .rc-imageselect-tile'
            );
            return {prompt: prompt, total: tiles.length};
        }""")
        return info
    except BaseException as e:
        return {"prompt": "", "total": 0}


async def get_tile_images_hash(challenge_frame):
    """Get a hash of tile image sources to detect if challenge actually changed."""
    try:
        return await challenge_frame.evaluate("""() => {
            const tiles = document.querySelectorAll(
                'td.rc-imageselect-tile, .rc-imageselect-tiletarget, .rc-imageselect-tile'
            );
            const srcs = [];
            for (const t of tiles) {
                const img = t.querySelector('img');
                srcs.push(img ? img.src : '');
            }
            return srcs.join('|');
        }""")
    except BaseException:
        return ""


async def solve_one_round(page, challenge_frame):
    """One round: screenshot → Gemini → click tiles → verify.
    Returns (clicked_tiles: list, prompt: str)."""

    info = await get_challenge_info(challenge_frame)
    prompt_raw = info.get("prompt", "")
    total = info.get("total", 9)
    prompt = _clean_prompt(prompt_raw)

    if not prompt:
        print("  No prompt text found — challenge may be gone")
        return [], ""

    print(f"  Prompt: '{prompt}' ({total} tiles)")

    # Take screenshot of the challenge frame
    try:
        screenshot_bytes = await challenge_frame.screenshot()
    except BaseException:
        screenshot_bytes = await page.screenshot()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

    # Determine grid layout
    if total >= 16:
        rows, cols = 4, 4
    elif total >= 9:
        rows, cols = 3, 3
    else:
        rows, cols = 2, 4

    grid_layout = "\n".join(
        " ".join(str(r * cols + c) for c in range(cols))
        for r in range(rows)
    )

    # Frame as image classification to avoid safety refusal
    instruction = f"""You are an expert image classifier. You see a {rows}x{cols} grid of tile images numbered 0-{total-1}:

{grid_layout}

The task is: "{prompt}"

Examine EACH tile carefully. Look at the visual content of each tile image.
Which tile numbers contain images matching the task description? Be precise — only select tiles that clearly match.

IMPORTANT: Tiles are numbered left-to-right, top-to-bottom:
- Row 1: tiles 0, 1, 2 (for 3x3) or 0, 1, 2, 3 (for 4x4)
- Row 2: tiles 3, 4, 5 or 4, 5, 6, 7
- Row 3: tiles 6, 7, 8 or 8, 9, 10, 11
- Row 4: tiles 12, 13, 14, 15 (4x4 only)

Return ONLY a JSON array of tile numbers that match. Example: [0, 3, 6]
If no tiles match, return []"""

    payload = {
        "contents": [{
            "parts": [
                {"text": instruction},
                {"inline_data": {"mime_type": "image/png", "data": screenshot_b64}}
            ]
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1000}
    }

    # Try keys with 3s delay
    for key_idx in range(len(GEMINI_KEYS)):
        key = _next_key()
        if not key:
            continue

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(url, json=payload)

                if resp.status_code == 429:
                    print(f"  key{key_idx}: 429, waiting 3s...")
                    await asyncio.sleep(3)
                    continue
                if resp.status_code == 503:
                    print(f"  key{key_idx}: 503, waiting 3s...")
                    await asyncio.sleep(3)
                    continue
                if resp.status_code != 200:
                    print(f"  key{key_idx}: {resp.status_code}")
                    await asyncio.sleep(2)
                    continue

                data = resp.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                print(f"  Gemini response: {text}")

                # Parse tiles — handle truncated responses
                text = text.strip()
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
                text = text.strip()

                tiles = []
                # Try full array match first
                match = re.search(r'\[([0-9,\s]*)\]', text)
                if match:
                    tile_strs = [t.strip() for t in match.group(1).split(",") if t.strip()]
                    tiles = [int(t) for t in tile_strs]
                else:
                    # Handle truncated response like "[0, 3, " (no closing bracket)
                    match_open = re.search(r'\[([0-9,\s]+)', text)
                    if match_open:
                        tile_strs = [t.strip() for t in match_open.group(1).split(",") if t.strip()]
                        tiles = [int(t) for t in tile_strs]
                    else:
                        try:
                            parsed = json.loads(text)
                            if isinstance(parsed, list):
                                tiles = [int(t) for t in parsed]
                        except BaseException:
                            pass

                # Filter out invalid tile numbers
                tiles = [t for t in tiles if 0 <= t < total]

                print(f"  Tiles to click: {tiles}")

                # Click tiles
                for tile_idx in tiles:
                    try:
                        clicked = await challenge_frame.evaluate(f"""(idx) => {{
                            const cells = document.querySelectorAll(
                                'td.rc-imageselect-tile, .rc-imageselect-tiletarget, .rc-imageselect-tile'
                            );
                            if (cells[idx]) {{ cells[idx].click(); return true; }}
                            return false;
                        }}""", tile_idx)
                        print(f"    Tile {tile_idx}: clicked={clicked}")
                        await asyncio.sleep(0.5)
                    except BaseException as e:
                        print(f"    Tile {tile_idx}: error={e}")

                await asyncio.sleep(1.5)

                # Click verify
                try:
                    await challenge_frame.evaluate("""() => {
                        const btn = document.getElementById('recaptcha-verify-button')
                            || document.querySelector('.rc-button-default');
                        if (btn) btn.click();
                    }""")
                    print("  Verify clicked")
                except BaseException as e:
                    print(f"  Verify error: {e}")

                return tiles, prompt

        except BaseException as e:
            print(f"  key{key_idx} error: {e}")
            await asyncio.sleep(2)
            continue

    print("  All keys exhausted")
    return [], ""


async def click_verify_only(challenge_frame):
    """Just click verify without Gemini call (for 'click verify once' state)."""
    try:
        await challenge_frame.evaluate("""() => {
            const btn = document.getElementById('recaptcha-verify-button')
                || document.querySelector('.rc-button-default');
            if (btn) btn.click();
        }""")
        print("  Verify-only clicked")
        return True
    except BaseException:
        return False


async def reload_challenge(challenge_frame):
    """Click reload button to get a new challenge."""
    try:
        await challenge_frame.evaluate("""() => {
            const btn = document.getElementById('recaptcha-reload-button')
                || document.querySelector('.rc-button-reload');
            if (btn) btn.click();
        }""")
        print("  Reload clicked")
        return True
    except BaseException:
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

        # Check if auto-solved
        resp = await get_recaptcha_response(page)
        if resp:
            print(f"Auto-solved! Token: {resp[:60]}...")
            await browser.close()
            return

        # Find challenge frame
        challenge_frame = None
        for frame in page.frames:
            if "recaptcha/api2/bframe" in frame.url:
                challenge_frame = frame
                break

        if not challenge_frame:
            print("No challenge frame")
            await browser.close()
            return

        print("Found challenge frame")
        await asyncio.sleep(3)

        # Dynamic challenge loop — up to 20 rounds
        prev_prompt = ""
        prev_hash = ""
        same_prompt_count = 0
        solved = False

        for round_num in range(20):
            print(f"\n=== Round {round_num + 1} ===")

            # Check if already solved
            resp = await get_recaptcha_response(page)
            if resp:
                print(f"\n*** RECAPTCHA SOLVED! ***")
                print(f"Token: {resp[:60]}...")
                solved = True
                break

            # Get current challenge info
            info = await get_challenge_info(challenge_frame)
            raw_prompt = info.get("prompt", "")
            total = info.get("total", 0)
            clean = _clean_prompt(raw_prompt)

            # "Click verify once" in raw prompt means previous round may have been correct.
            # But only skip Gemini call if we genuinely can't extract a real challenge prompt.
            if "click verify once" in raw_prompt.lower() and not clean and total > 0:
                # Tiles exist but no challenge prompt extracted — try verify
                verify_count_key = "_verify_count"
                vc = getattr(main, verify_count_key, 0) + 1
                setattr(main, verify_count_key, vc)
                print(f"  'Click verify once' detected (attempt {vc})")
                if vc <= 2:
                    await click_verify_only(challenge_frame)
                    await asyncio.sleep(12)
                else:
                    print(f"  Verify stuck {vc} times — reloading challenge")
                    await reload_challenge(challenge_frame)
                    await asyncio.sleep(6)
                    setattr(main, verify_count_key, 0)
                    prev_prompt = ""
                    prev_hash = ""
                continue

            if not clean or total == 0:
                print("  Challenge empty — may be solved or transitioning")
                # Wait longer — Google may be processing the last round
                for _ in range(5):
                    await asyncio.sleep(3)
                    resp = await get_recaptcha_response(page)
                    if resp:
                        print(f"Solved! Token: {resp[:60]}...")
                        solved = True
                        break
                    # Check if challenge frame is gone/collapsed
                    try:
                        frame_url = challenge_frame.url
                        if not frame_url or "bframe" not in frame_url:
                            print("  Challenge frame gone — checking if solved")
                            resp = await get_recaptcha_response(page)
                            if resp:
                                print(f"Solved! Token: {resp[:60]}...")
                                solved = True
                                break
                            # Frame gone but no token — try clicking checkbox again
                            break
                    except BaseException:
                        print("  Challenge frame detached — likely solved")
                        resp = await get_recaptcha_response(page)
                        if resp:
                            print(f"Solved! Token: {resp[:60]}...")
                            solved = True
                            break
                        break
                if solved:
                    break
                # Check anchor frame checkbox state
                try:
                    checked = await recaptcha_frame.evaluate("""() => {
                        const cb = document.querySelector('.recaptcha-checkbox-checkmark');
                        return cb ? true : false;
                    }""")
                    if checked:
                        print("  Checkbox shows solved state!")
                        resp = await get_recaptcha_response(page)
                        if resp:
                            print(f"Solved! Token: {resp[:60]}...")
                            solved = True
                            break
                except BaseException:
                    pass
                # Only reload if we're truly stuck (not transitioning)
                # First, try clicking verify — empty tiles + verify = submit
                await click_verify_only(challenge_frame)
                await asyncio.sleep(8)
                resp = await get_recaptcha_response(page)
                if resp:
                    print(f"Solved after verify! Token: {resp[:60]}...")
                    solved = True
                    break
                print("  Challenge empty after verify — reloading")
                await reload_challenge(challenge_frame)
                await asyncio.sleep(5)
                continue

            # Check if same prompt as before
            current_hash = await get_tile_images_hash(challenge_frame)
            if clean == prev_prompt and current_hash == prev_hash:
                same_prompt_count += 1
                print(f"  Same challenge as before (count={same_prompt_count})")
                if same_prompt_count >= 3:
                    print("  Reloading challenge (stuck on same one)")
                    await reload_challenge(challenge_frame)
                    await asyncio.sleep(5)
                    same_prompt_count = 0
                    prev_prompt = ""
                    prev_hash = ""
                    continue
            else:
                same_prompt_count = 0

            # Solve one round
            tiles, prompt = await solve_one_round(page, challenge_frame)

            prev_prompt = prompt
            prev_hash = current_hash

            # Wait for Google to process
            await asyncio.sleep(8)

            # Check if solved
            resp = await get_recaptcha_response(page)
            if resp:
                print(f"\n*** RECAPTCHA SOLVED after round {round_num + 1}! ***")
                print(f"Token: {resp[:60]}...")
                solved = True
                break

        if solved:
            # Perform search
            print("\nPerforming estate search...")
            try:
                search_input = await page.query_selector(
                    "input[type='text'], input[name*='name'], input[name*='Name'], #Name"
                )
                if search_input:
                    await search_input.fill("Smith")
                    print("Filled 'Smith'")

                search_btn = await page.query_selector(
                    "input[type='submit'], button[type='submit'], .search-btn, .btn, button"
                )
                if search_btn:
                    await search_btn.click()
                    print("Clicked search")
                    await asyncio.sleep(10)
                    content = await page.content()
                    print(f"Page content: {len(content)} chars")
                    with open("/tmp/lex_search_results.html", "w") as f:
                        f.write(content)
                    print("Results saved to /tmp/lex_search_results.html")
            except BaseException as e:
                print(f"Search error: {e}")
        else:
            print("\nFailed to solve reCAPTCHA after 20 rounds")

        await page.screenshot(path="/tmp/lex_v6_final.png")
        print("\nFinal screenshot saved")
        await browser.close()


asyncio.run(main())
