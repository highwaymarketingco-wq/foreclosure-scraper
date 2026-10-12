"""LEX reCAPTCHA Audio Solver v16.

Instead of image classification (Gemini accuracy too low), use the audio challenge:
1. Click reCAPTCHA checkbox
2. If challenge appears, switch to audio mode
3. Download the audio file
4. Use Google Web Speech API or whisper.cpp for STT
5. Type the numbers
6. Verify

This is more reliable than image classification — audio challenges are 
simpler (just numbers/letters) and speech-to-text is very accurate.
"""
import asyncio
import base64
import json
import os
import re
import sys
import time
import urllib.parse

import httpx
from patchright.async_api import async_playwright

LEXINGTON_URL = "https://www.lex-co.com/ProbateSearch/estates"


async def get_recaptcha_response(page):
    """Check if reCAPTCHA is solved (has token)."""
    try:
        return await page.evaluate("() => document.getElementById('g-recaptcha-response')?.value || ''")
    except BaseException:
        return ""


async def solve_audio_challenge(page, challenge_frame):
    """Switch to audio mode and solve via speech-to-text."""
    
    # Step 1: Click the "Audio" button to switch to audio challenge
    print("  Switching to audio challenge...")
    try:
        # The audio button is in the challenge frame
        clicked = await challenge_frame.evaluate("""() => {
            // Find the audio button
            const audioBtn = document.querySelector('#recaptcha-audio-button') 
                || document.querySelector('.rc-button-audio');
            if (audioBtn) {
                audioBtn.click();
                return true;
            }
            // Try by text
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

    await asyncio.sleep(3)

    # Step 2: Get the audio source URL
    print("  Getting audio source...")
    audio_url = None
    try:
        audio_url = await challenge_frame.evaluate("""() => {
            const audio = document.querySelector('audio source') || document.querySelector('audio');
            if (audio) return audio.src || audio.getAttribute('src');
            // Try to find download link
            const link = document.querySelector('.rc-audiochallenge-tdownload-link');
            if (link) return link.href;
            return null;
        }""")
    except BaseException as e:
        print(f"  Audio source error: {e}")

    if not audio_url:
        print("  No audio URL found — trying alternative...")
        # Take screenshot to debug
        try:
            screenshot_bytes = await challenge_frame.screenshot()
            with open("/tmp/lex_audio_debug.png", "wb") as f:
                f.write(screenshot_bytes)
            print("  Screenshot saved to /tmp/lex_audio_debug.png")
        except BaseException:
            pass
        
        # Try getting the page HTML
        try:
            html = await challenge_frame.evaluate("() => document.documentElement.outerHTML.substring(0, 3000)")
            print(f"  Frame HTML: {html[:1000]}")
        except BaseException:
            pass
        return False

    print(f"  Audio URL: {audio_url[:100]}...")

    # Step 3: Download the audio file
    print("  Downloading audio...")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Need cookies from the browser session
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
            
            # Save to temp file
            with open("/tmp/lex_audio.mp3", "wb") as f:
                f.write(audio_data)
    except Exception as e:
        print(f"  Audio download error: {e}")
        return False

    # Step 4: Speech-to-text — try multiple approaches
    transcript = await speech_to_text("/tmp/lex_audio.mp3", audio_data)
    if not transcript:
        print("  STT failed — no transcript")
        return False

    print(f"  Transcript: '{transcript}'")

    # Step 5: Clean up the transcript — reCAPTCHA audio is numbers/letters
    # Remove common false words
    transcript = transcript.strip().lower()
    # reCAPTCHA audio usually says "Type the numbers you hear" — we need just the numbers
    # Remove non-alphanumeric
    clean = re.sub(r'[^a-z0-9\s]', '', transcript)
    # Remove common filler words
    filler = ['the', 'numbers', 'you', 'hear', 'type', 'please', 'enter', 'below']
    words = [w for w in clean.split() if w not in filler]
    answer = "".join(words)
    
    # If it's too long, just take the first few chars
    if len(answer) > 10:
        answer = answer[:10]
    
    print(f"  Answer: '{answer}'")

    if not answer:
        print("  No answer extracted from transcript")
        return False

    # Step 6: Type the answer into the input field
    print("  Typing answer...")
    try:
        # Find the audio response input
        typed = await challenge_frame.evaluate(f"""(answer) => {{
            const input = document.getElementById('audio-response') 
                || document.querySelector('input[name="audio-response"]')
                || document.querySelector('#response');
            if (input) {{
                input.value = answer;
                input.dispatchEvent(new Event('input', {{bubbles: true}}));
                input.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
            return false;
        }}""", answer)
        
        if not typed:
            print("  Could not find audio response input")
            return False
        print("  Answer typed")
    except BaseException as e:
        print(f"  Type error: {e}")
        return False

    # Step 7: Click verify
    await asyncio.sleep(1)
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

    print("  Not solved after verify — may need another attempt")
    return False


async def speech_to_text(filepath, audio_data):
    """Try multiple STT approaches."""
    
    # Approach 1: Groq Whisper API (fast, free tier, user has key)
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        # Try loading from file
        try:
            with open(os.path.expanduser("~/.secrets/groq_api_key.txt")) as f:
                groq_key = f.read().strip()
        except Exception:
            pass
        if not groq_key:
            try:
                with open(".secrets/groq_api_key.txt") as f:
                    groq_key = f.read().strip()
            except Exception:
                pass

    if groq_key:
        try:
            print("  Trying Groq Whisper API...")
            # Convert to base64
            audio_b64 = base64.b64encode(audio_data).decode()
            
            # Groq Whisper endpoint
            # First write to temp file and send as multipart
            import tempfile
            
            # Determine content type from audio data
            content_type = "audio/mpeg"
            if audio_data[:4] == b'RIFF':
                content_type = "audio/wav"
            
            files = {
                "file": ("audio.mp3", audio_data, content_type),
                "model": (None, "whisper-large-v3"),
                "language": (None, "en"),
                "response_format": (None, "json"),
                "temperature": (None, "0"),
                "prompt": (None, "A distorted robotic voice reads out a sequence of numbers and single letters. Transcribe ONLY the numbers and letters, nothing else. Example: 7 3 9 2 5 1"),
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
                    if transcript:
                        print(f"  Groq Whisper: '{transcript}'")
                        return transcript
                else:
                    print(f"  Groq API: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"  Groq Whisper error: {e}")

    # Approach 2: Use Wit.ai (free STT API)
    wit_token = os.environ.get("WIT_AI_TOKEN", "")
    if wit_token:
        try:
            print("  Trying Wit.ai...")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.wit.ai/speech",
                    headers={
                        "Authorization": f"Bearer {wit_token}",
                        "Content-Type": "audio/mpeg3",
                    },
                    content=audio_data
                )
                if resp.status_code == 200:
                    text = resp.json().get("text", "")
                    if text:
                        return text
        except Exception as e:
            print(f"  Wit.ai error: {e}")

    # Approach 3: Use local whisper if available
    try:
        print("  Trying local whisper...")
        proc = await asyncio.create_subprocess_exec(
            "whisper", filepath, "--model", "tiny", "--language", "en",
            "--output_format", "txt", "--output_dir", "/tmp/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        txt_path = filepath.replace(".mp3", ".txt")
        if os.path.exists(txt_path):
            with open(txt_path) as f:
                return f.read().strip()
    except Exception as e:
        print(f"  Whisper error: {e}")

    # Approach 4: Use Google Cloud Speech via gcloud CLI
    try:
        print("  Trying gcloud speech...")
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c",
            f"""
import speech_recognition as sr
r = sr.Recognizer()
with sr.AudioFile("{filepath}") as source:
    audio = r.record(source)
try:
    print(r.recognize_google(audio))
except Exception as e:
    print(f"ERR: {{e}}")
""",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        result = stdout.decode().strip()
        if result and not result.startswith("ERR:"):
            return result
    except Exception as e:
        print(f"  speech_recognition error: {e}")

    return None


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
        await asyncio.sleep(8)

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
            print("No challenge frame found — may have auto-solved")
            await browser.close()
            return

        print("Found challenge frame")

        # Try audio solver up to 8 times
        for attempt in range(8):
            print(f"\n=== Audio attempt {attempt+1} ===")
            
            # Re-find challenge frame each time (it detaches after failed verify)
            challenge_frame = None
            for frame in page.frames:
                if "recaptcha/api2/bframe" in frame.url:
                    challenge_frame = frame
                    break
            
            if not challenge_frame:
                print("  No challenge frame — checking if auto-solved")
                resp = await get_recaptcha_response(page)
                if resp:
                    print(f"  SOLVED! Token: {resp[:60]}...")
                    break
                # Challenge frame gone, no token — session burned.
                # Reload entire page and start fresh.
                print("  Session burned — reloading entire page...")
                await page.goto(LEXINGTON_URL, timeout=60000)
                await asyncio.sleep(5)
                # Re-click reCAPTCHA checkbox
                anchor_frame = None
                for frame in page.frames:
                    if "recaptcha/api2/anchor" in frame.url:
                        anchor_frame = frame
                        break
                if anchor_frame:
                    try:
                        await anchor_frame.click(".recaptcha-checkbox-border")
                        print("  Checkbox clicked after reload")
                        await asyncio.sleep(5)
                    except BaseException as e:
                        print(f"  Checkbox error after reload: {e}")
                continue
            
            solved = await solve_audio_challenge(page, challenge_frame)
            if solved:
                print("\nreCAPTCHA SOLVED via audio!")
                
                # Now do the probate search
                print("Performing probate search...")
                try:
                    # Fill date range — last 2 years
                    await page.fill("#DateFrom", "01/01/2024")
                    await page.fill("#DateTo", "12/31/2026")
                    await asyncio.sleep(1)
                    
                    # Click search button
                    await page.click("button[type='submit'], input[type='submit'], #searchBtn")
                    await asyncio.sleep(10)
                    
                    # Check results
                    html = await page.content()
                    print(f"Page length: {len(html)}")
                    
                    # Save results
                    with open("/tmp/lex_results.html", "w") as f:
                        f.write(html)
                    print("Results saved to /tmp/lex_results.html")
                    
                except Exception as e:
                    print(f"Search error: {e}")
                
                break
            
            # Reload challenge for next attempt
            if attempt < 7:
                print("Reloading challenge...")
                # Re-find frame again before reloading
                challenge_frame = None
                for frame in page.frames:
                    if "recaptcha/api2/bframe" in frame.url:
                        challenge_frame = frame
                        break
                if challenge_frame:
                    try:
                        await challenge_frame.evaluate("""() => {
                            const btn = document.getElementById('recaptcha-reload-button')
                                || document.querySelector('.rc-button-reload');
                            if (btn) btn.click();
                        }""")
                    except BaseException as e:
                        print(f"  Reload error: {e}")
                await asyncio.sleep(3)

        await browser.close()
        print("Done")


if __name__ == "__main__":
    asyncio.run(main())
