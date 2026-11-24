#!/usr/bin/env python3
"""Investigate Lexington Probate reCAPTCHA anti-bot block.

Claude says: Google's anti-bot engine refuses audio ("automated queries, try again later").
This is NOT a timing issue - it's Google detecting automation.

APPROACHES TO TEST:
1. Detect the anti-bot message
2. Try headful mode (more human-like)
3. Try different user agents
4. Try residential proxy rotation (if available)
5. Add more human-like delays/mouse movements
"""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from patchright.async_api import async_playwright
import structlog

log = structlog.get_logger()

URL = "https://www.lex-co.com/ProbateSearch/estates"


async def test_antibot_detection():
    """Test if we can detect Google's anti-bot message."""
    
    async with async_playwright() as pw:
        # Try HEADFUL first (more human-like)
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        
        page = await context.new_page()
        
        log.info("navigate", url=URL)
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        
        # Wait for reCAPTCHA to load
        log.info("waiting_for_recaptcha")
        await asyncio.sleep(5)
        
        # Find anchor frame (checkbox)
        anchor_frame = None
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                anchor_frame = frame
                break
        
        if not anchor_frame:
            log.error("no_anchor_frame")
            await browser.close()
            return
        
        log.info("found_anchor_frame", url=anchor_frame.url)
        
        # Click checkbox
        await asyncio.sleep(2)
        try:
            await anchor_frame.evaluate("""() => {
                const cb = document.querySelector('.recaptcha-checkbox-border') 
                        || document.getElementById('recaptcha-anchor');
                if (cb) cb.click();
            }""")
            log.info("clicked_checkbox")
        except Exception as exc:
            log.error("checkbox_click_failed", error=str(exc))
            await browser.close()
            return
        
        # Wait for challenge or auto-solve
        await asyncio.sleep(5)
        
        # Check if challenge appeared
        challenge_frame = None
        for frame in page.frames:
            if "recaptcha/api2/bframe" in frame.url:
                challenge_frame = frame
                break
        
        if not challenge_frame:
            log.info("no_challenge_maybe_autosolved")
            # Check token
            token = await page.evaluate("() => document.getElementById('g-recaptcha-response')?.value || ''")
            if token:
                log.info("✅ AUTO-SOLVED!", token_len=len(token))
            else:
                log.warning("⚠️  No challenge but no token either")
            await browser.close()
            return
        
        log.info("challenge_appeared", url=challenge_frame.url)
        
        # Click audio button
        await asyncio.sleep(2)
        try:
            clicked = await challenge_frame.evaluate("""() => {
                const btn = document.querySelector('#recaptcha-audio-button')
                          || document.querySelector('.rc-button-audio');
                if (btn) { btn.click(); return true; }
                return false;
            }""")
            if clicked:
                log.info("clicked_audio_button")
            else:
                log.error("audio_button_not_found")
                await browser.close()
                return
        except Exception as exc:
            log.error("audio_click_failed", error=str(exc))
            await browser.close()
            return
        
        # Wait and check for anti-bot message
        await asyncio.sleep(3)
        
        # Check for error messages
        try:
            error_text = await challenge_frame.evaluate("""() => {
                // Check for error divs
                const errors = document.querySelectorAll('.rc-audiochallenge-error-message, .rc-doscaptcha-header-text, [class*="error"]');
                for (const e of errors) {
                    if (e.textContent && e.textContent.trim()) {
                        return e.textContent.trim();
                    }
                }
                
                // Check if audio actually loaded
                const audioSrc = document.querySelector('audio source')?.src || document.querySelector('audio')?.src;
                if (!audioSrc) {
                    return "NO_AUDIO_SRC";
                }
                
                return null;
            }""")
            
            if error_text:
                if "automated" in error_text.lower() or "try again" in error_text.lower():
                    log.error("🚫 ANTI-BOT DETECTED", message=error_text)
                else:
                    log.warning("error_message_found", text=error_text)
            else:
                # Audio loaded successfully
                audio_url = await challenge_frame.evaluate("""() => {
                    const a = document.querySelector('audio source') || document.querySelector('audio');
                    if (a) return a.src || a.getAttribute('src');
                    return null;
                }""")
                
                if audio_url:
                    log.info("✅ AUDIO LOADED", url_prefix=audio_url[:80])
                else:
                    log.warning("⚠️  No error but no audio either")
                    
        except Exception as exc:
            log.error("error_check_failed", error=str(exc))
        
        # Keep browser open for manual inspection
        log.info("browser_open_for_inspection", message="Press Ctrl+C to close")
        try:
            await asyncio.sleep(300)
        except KeyboardInterrupt:
            pass
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_antibot_detection())
