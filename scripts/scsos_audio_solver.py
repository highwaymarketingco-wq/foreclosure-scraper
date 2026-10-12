"""SC SOS Entity Search — reCAPTCHA Audio Solver.

Uses Groq Whisper API to solve reCAPTCHA v2 audio challenge on
businessfilings.sc.gov, then searches for entities.

Flow:
1. Load search page with patchright headless=False
2. Fill entity name, click search
3. If reCAPTCHA appears, switch to audio
4. Download audio, transcribe via Groq Whisper
5. Type answer, verify
6. Parse results
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

SC_SOS_URL = "https://businessfilings.sc.gov/BusinessFiling/Entity/Search"

# Test entity names to search
ENTITY_NAMES = [
    "Smith Properties LLC",
    "Johnson Real Estate",
    "Carolina Investment Group",
    "Palmetto Holdings",
    "Summit Property Management",
]


async def get_recaptcha_response(page):
    """Check if reCAPTCHA is solved (has token)."""
    try:
        return await page.evaluate(
            "() => document.getElementById('g-recaptcha-response')?.value || ''"
        )
    except BaseException:
        return ""


async def solve_audio_challenge(page, challenge_frame):
    """Switch to audio mode and solve via Groq Whisper STT."""

    # Step 1: Click the "Audio" button to switch to audio challenge
    print("  Switching to audio challenge...")
    try:
        clicked = await challenge_frame.evaluate("""() => {
            const audioBtn = document.querySelector('#recaptcha-audio-button')
                || document.querySelector('.rc-button-audio');
            if (audioBtn) {
                audioBtn.click();
                return true;
            }
            const btns = document.querySelectorAll('button, a');
            for (const b of btns) {
                if (b.textContent && b.textContent.toLowerCase().includes('audio')) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if not clicked:
            print("  Could not find audio button")
            return False
        print("  Audio button clicked")
    except BaseException as e:
        print(f"  Audio button error: {e}")
        return False

    await asyncio.sleep(4)

    # Step 2: Get the audio source URL
    print("  Getting audio source...")
    audio_url = None
    try:
        audio_url = await challenge_frame.evaluate("""() => {
            const audio = document.querySelector('audio source') || document.querySelector('audio');
            if (audio) return audio.src || audio.getAttribute('src');
            const link = document.querySelector('.rc-audiochallenge-tdownload-link');
            if (link) return link.href;
            return null;
        }""")
    except BaseException as e:
        print(f"  Audio source error: {e}")

    if not audio_url:
        print("  No audio URL found")
        # Debug: dump frame HTML
        try:
            html = await challenge_frame.evaluate(
                "() => document.documentElement.outerHTML.substring(0, 2000)"
            )
            print(f"  Frame HTML snippet: {html[:800]}")
        except BaseException:
            pass
        return False

    print(f"  Audio URL: {audio_url[:80]}...")

    # Step 3: Download the audio file
    print("  Downloading audio...")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            cookies = await page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            headers = {
                "Referer": "https://www.google.com/recaptcha/api2/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            if cookie_str:
                headers["Cookie"] = cookie_str

            resp = await client.get(audio_url, headers=headers)
            if resp.status_code != 200:
                print(f"  Audio download failed: {resp.status_code}")
                return False

            audio_data = resp.content
            print(f"  Downloaded {len(audio_data)} bytes of audio")

            with open("/tmp/scsos_audio.mp3", "wb") as f:
                f.write(audio_data)
    except Exception as e:
        print(f"  Audio download error: {e}")
        return False

    # Step 4: Speech-to-text via Groq Whisper
    transcript = await speech_to_text_groq(audio_data)
    if not transcript:
        print("  STT failed — no transcript")
        return False

    print(f"  Groq Whisper transcript: '{transcript}'")

    # Step 5: Clean up the transcript
    # reCAPTCHA audio is a sequence of numbers and/or letters
    transcript = transcript.strip().lower()
    # Remove non-alphanumeric
    clean = re.sub(r'[^a-z0-9\s]', '', transcript)
    # Remove common filler words
    filler = {
        'the', 'numbers', 'you', 'hear', 'type', 'please', 'enter', 'below',
        'or', 'and', 'digits', 'letters', 'sequence', 'of', 'in', 'to',
        'press', 'key', 'after', 'each', 'number',
    }
    words = [w for w in clean.split() if w not in filler]
    answer = "".join(words)

    if len(answer) > 12:
        answer = answer[:12]

    print(f"  Answer: '{answer}'")

    if not answer or len(answer) < 2:
        print("  Answer too short")
        return False

    # Step 6: Type the answer
    print("  Typing answer...")
    try:
        typed = await challenge_frame.evaluate("""(answer) => {
            const input = document.getElementById('audio-response')
                || document.querySelector('input[name="audio-response"]')
                || document.querySelector('#response');
            if (input) {
                input.value = answer;
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }
            return false;
        }""", answer)

        if not typed:
            print("  Could not find audio response input")
            return False
        print("  Answer typed")
    except BaseException as e:
        print(f"  Type error: {e}")
        return False

    # Step 7: Click verify
    await asyncio.sleep(1.5)
    try:
        await challenge_frame.evaluate("""() => {
            const btn = document.getElementById('recaptcha-verify-button')
                || document.querySelector('.rc-button-default');
            if (btn) btn.click();
        }""")
        print("  Verify clicked")
    except BaseException as e:
        print(f"  Verify error: {e}")
        return False

    await asyncio.sleep(5)

    # Step 8: Check if solved
    resp = await get_recaptcha_response(page)
    if resp:
        print(f"  SOLVED! Token: {resp[:60]}...")
        return True

    print("  Not solved after verify")
    return False


async def speech_to_text_groq(audio_data):
    """Use Groq Whisper API for speech-to-text."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        for path in ["~/.secrets/groq_api_key.txt", ".secrets/groq_api_key.txt"]:
            try:
                with open(os.path.expanduser(path)) as f:
                    groq_key = f.read().strip()
                    if groq_key:
                        break
            except Exception:
                pass

    if not groq_key:
        print("  No Groq API key found")
        return None

    try:
        content_type = "audio/mpeg"
        if audio_data[:4] == b'RIFF':
            content_type = "audio/wav"

        files = {
            "file": ("audio.mp3", audio_data, content_type),
            "model": (None, "whisper-large-v3"),
            "language": (None, "en"),
            "response_format": (None, "json"),
            "temperature": (None, "0"),
            "prompt": (None, "The following audio contains a sequence of numbers and letters. Please transcribe them exactly."),
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                files=files,
            )
            if resp.status_code == 200:
                data = resp.json()
                transcript = data.get("text", "")
                return transcript
            else:
                print(f"  Groq API: {resp.status_code} {resp.text[:200]}")
                return None
    except Exception as e:
        print(f"  Groq Whisper error: {e}")
        return None


async def find_challenge_frame(page):
    """Find the reCAPTCHA challenge frame."""
    for frame in page.frames:
        if "recaptcha/api2/bframe" in frame.url:
            return frame
    return None


async def find_anchor_frame(page):
    """Find the reCAPTCHA anchor frame."""
    for frame in page.frames:
        if "recaptcha/api2/anchor" in frame.url:
            return frame
    return None


async def search_entity(page, entity_name, max_captcha_attempts=8):
    """Search for one entity, solving reCAPTCHA if needed."""
    print(f"\n--- Searching: {entity_name} ---")

    # Fill search box
    try:
        await page.fill("#SearchTextBox", entity_name)
        await asyncio.sleep(0.5)
    except BaseException as e:
        print(f"  Fill error: {e}")
        return None

    # Click search button
    try:
        await page.click("#EntitySearchButton")
    except BaseException:
        try:
            await page.evaluate("document.getElementById('EntitySearchButton')?.click()")
        except BaseException as e:
            print(f"  Search button error: {e}")
            return None

    await asyncio.sleep(5)

    # Check for reCAPTCHA
    anchor_frame = await find_anchor_frame(page)

    if anchor_frame:
        # Click the checkbox
        try:
            await anchor_frame.click(".recaptcha-checkbox-border")
            print("  Clicked reCAPTCHA checkbox")
        except BaseException as e:
            print(f"  Checkbox click error: {e}")
        await asyncio.sleep(4)

    # Check if auto-solved or no captcha needed
    resp = await get_recaptcha_response(page)
    if resp:
        print(f"  Auto-solved! Token: {resp[:40]}...")
    else:
        # Try audio solver
        challenge_frame = await find_challenge_frame(page)
        if challenge_frame:
            print("  Challenge frame found — attempting audio solve")
            for attempt in range(max_captcha_attempts):
                print(f"\n  === Audio attempt {attempt+1} ===")

                # Re-find frame each time
                challenge_frame = await find_challenge_frame(page)
                if not challenge_frame:
                    print("  No challenge frame — checking if solved")
                    resp = await get_recaptcha_response(page)
                    if resp:
                        print(f"  SOLVED! Token: {resp[:40]}...")
                    break

                solved = await solve_audio_challenge(page, challenge_frame)
                if solved:
                    break

                # Reload challenge
                if attempt < max_captcha_attempts - 1:
                    print("  Reloading challenge...")
                    challenge_frame = await find_challenge_frame(page)
                    if challenge_frame:
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
            print("  No challenge frame — page may have loaded results directly")

    # Re-click search if captcha was solved
    if resp or await get_recaptcha_response(page):
        print("  reCAPTCHA solved — submitting search again")
        try:
            await page.fill("#SearchTextBox", entity_name)
            await page.click("#EntitySearchButton")
            await asyncio.sleep(8)
        except BaseException as e:
            print(f"  Re-search error: {e}")

    # Parse results
    html = await page.content()
    print(f"  Page length: {len(html)}")

    # Save results
    with open("/tmp/scsos_results.html", "w") as f:
        f.write(html)

    # Quick parse for entity rows
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tr")
    entities = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        name = cells[0].get_text(strip=True)
        status = cells[-1].get_text(strip=True) if cells else ""
        if name and len(name) > 2:
            entities.append({"name": name, "status": status})

    print(f"  Found {len(entities)} entities")
    return entities


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        print(f"Loading SC SOS search page: {SC_SOS_URL}")
        await page.goto(SC_SOS_URL, timeout=60000)
        await asyncio.sleep(5)

        all_entities = []
        for name in ENTITY_NAMES:
            result = await search_entity(page, name)
            if result:
                all_entities.extend(result)
            await asyncio.sleep(2)

        # Save all results
        with open("/tmp/scsos_all_entities.json", "w") as f:
            json.dump(all_entities, f, indent=2)

        print(f"\nTotal entities found: {len(all_entities)}")
        print(f"Saved to /tmp/scsos_all_entities.json")

        await browser.close()
        print("Done")


if __name__ == "__main__":
    asyncio.run(main())
