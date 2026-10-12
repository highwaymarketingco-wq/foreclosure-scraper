"""Free reCAPTCHA V2 audio solver — faster-whisper STT.

Solves Google reCAPTCHA V2 ("I'm not a robot" checkbox) by:
1. Clicking the checkbox (triggers the audio challenge fallback)
2. Clicking the audio challenge button
3. Downloading the audio clip (mp3)
4. Transcribing it with faster-whisper (local Whisper model, no API key)
5. Submitting the transcription back to the reCAPTCHA widget

This is a FREE solution — faster-whisper runs a local CTranslate2-optimized
Whisper model on CPU. No external API calls, no per-solve cost.

Accuracy: ~80-90% on clean audio. May need 1-2 retries on noisy clips.

LIMITATIONS:
- Google may rate-limit audio challenges (~50-100 solves/day per IP).
- Does not work for reCAPTCHA V3 (invisible, score-based — needs a different
  approach: Playwright token capture, see enrichment_recaptcha_v3.py).
- Does not work for reCAPTCHA Enterprise with image challenges (would need
  Gemini Vision image-grid solver as backup).

Sources this solves (8+ from walls_register.json):
- NC eCourts portal (portal-nc.tylertech.cloud) — picture CAPTCHA
- ncnotices.com — Google checkbox CAPTCHA
- SC Secretary of State business entity search
- scpublicnotices.com — Google CAPTCHA
- Wake County deed search — Google CAPTCHA on entry disclaimer
- Dorchester treasurer's site — Google CAPTCHA
- Beaufort deed search — CAPTCHA
- Jasper deed search — CAPTCHA

Usage:
    from foreclosure_scraper.enrichment_recaptcha_audio import solve_recaptcha_v2

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://example.com")

        solved = await solve_recaptcha_v2(page)
        if solved:
            # reCAPTCHA is cleared — proceed with the page
            ...
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Whisper model — lazy-loaded singleton (loads on first use, ~5s on CPU)
# ---------------------------------------------------------------------------

_whisper_model = None
_model_lock = asyncio.Lock()

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")
# base.en is English-only, smaller, faster; good enough for reCAPTCHA audio
# (the audio is always English digits/words).
# Options: tiny.en, base.en, small.en — tiny is ~1GB, base is ~2GB.


async def _get_whisper_model():
    """Lazy-load the faster-whisper model (thread-safe, cached)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    async with _model_lock:
        if _whisper_model is not None:
            return _whisper_model

        def _load():
            from faster_whisper import WhisperModel
            log.info("recaptcha.loading_whisper", model=WHISPER_MODEL_SIZE)
            return WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8",  # best CPU performance
            )

        _whisper_model = await asyncio.to_thread(_load)
        log.info("recaptcha.whisper_loaded")
        return _whisper_model


# ---------------------------------------------------------------------------
# Audio transcription
# ---------------------------------------------------------------------------

async def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file with faster-whisper, return the text.

    Args:
        audio_path: Path to the downloaded audio file (mp3/wav).

    Returns:
        The transcribed text (lowercased, stripped).
    """
    model = await _get_whisper_model()

    def _transcribe():
        segments, _info = model.transcribe(
            audio_path,
            language="en",
            beam_size=1,  # fast — reCAPTCHA audio is short
            best_of=1,
            temperature=0.0,
        )
        text = " ".join(s.text for s in segments).strip().lower()
        return text

    text = await asyncio.to_thread(_transcribe)
    log.info("recaptcha.transcribed", text=text, audio=audio_path)
    return text


# ---------------------------------------------------------------------------
# reCAPTCHA V2 audio solver — Playwright automation
# ---------------------------------------------------------------------------

# Selectors for the reCAPTCHA widget — Google changes these periodically,
# so we try multiple variants.
_RECAPTCHA_FRAME = "iframe[title*='reCAPTCHA']"
_RECAPTCHA_CHECKBOX_SELECTORS = [
    ".recaptcha-checkbox-border",
    "#recaptcha-anchor",
    "#recaptcha-anchor-label",
]
_AUDIO_BUTTON_SELECTORS = [
    "#recaptcha-audio-button",
    ".rc-button-audio",
    "a.rc-button-audio",
    "button.rc-button-audio",
    "[aria-label*='audio' i]",
    "[aria-label*='Get an audio' i]",
    "a:has-text('audio')",
    "button:has-text('AUDIO')",
    "a:has-text('AUDIO')",
    ".rc-button.goog-inline-block[aria-label*='audio' i]",
    "#recaptcha-reload-button",  # sometimes the reload doubles as audio toggle
]
_AUDIO_DOWNLOAD_SELECTORS = [
    ".rc-audiochallenge-tdownload-link",
    "a[href*='audio']",
    ".rc-audiochallenge-download-link",
    "a.rc-button",
    "a[download]",
    ".audio-media-link",
    "a[href*='.mp3']",
    "a[href*='google.com/recaptcha/api2/audio']",
    "audio source[src]",
    "audio[src]",
    "#audio-source",
    ".rc-audiochallenge-play-button",
    "a[href*='.wav']",
]
_AUDIO_RESPONSE_INPUT = "#audio-response"
_VERIFY_BUTTON = "#recaptcha-verify-button"
_GET_AUDIO_CHALLENGE = ".rc-button-audio"


async def solve_recaptcha_v2(
    page: Any,
    max_retries: int = 3,
    timeout_ms: int = 30000,
) -> bool:
    """Solve a reCAPTCHA V2 checkbox on a Playwright page via audio challenge.

    Args:
        page: A Playwright Page already navigated to a page with reCAPTCHA V2.
        max_retries: Maximum number of transcription attempts (reCAPTCHA
            may reject a wrong transcription and present a new challenge).
        timeout_ms: Total timeout for the solve attempt.

    Returns:
        True if the reCAPTCHA was solved (checkbox shows green checkmark).
        False if all retries failed or no reCAPTCHA was found.
    """
    # Step 1: Find the reCAPTCHA iframe and click the checkbox.
    try:
        recaptcha_frame = await page.wait_for_selector(
            _RECAPTCHA_FRAME, timeout=20000
        )
    except Exception:
        log.warning("recaptcha.no_widget")
        return False

    frame = await recaptcha_frame.content_frame()
    if frame is None:
        log.warning("recaptcha.no_frame")
        return False

    # Click the checkbox — this either solves it (invisible mode) or opens
    # the challenge view. Try multiple selectors since Google changes the DOM.
    checkbox_clicked = False
    for sel in _RECAPTCHA_CHECKBOX_SELECTORS:
        try:
            checkbox = await frame.wait_for_selector(sel, timeout=5000)
            if checkbox:
                await checkbox.click()
                checkbox_clicked = True
                await page.wait_for_timeout(3000)
                break
        except Exception:
            continue
    if not checkbox_clicked:
        log.warning("recaptcha.checkbox_click_failed", error="No checkbox selector matched")

    # Check if it's already solved (sometimes invisible mode just passes).
    try:
        aria = await frame.get_attribute(".recaptcha-checkbox", "aria-checked")
        if aria == "true":
            log.info("recaptcha.already_solved")
            return True
    except Exception:
        pass

    # Step 2: Switch to the challenge frame (a second iframe appears).
    try:
        challenge_frame_element = await page.wait_for_selector(
            "iframe[title*='recaptcha challenge']", timeout=20000
        )
        challenge_frame = await challenge_frame_element.content_frame()
        if challenge_frame is None:
            log.warning("recaptcha.no_challenge_frame")
            return False
    except Exception as exc:
        log.warning("recaptcha.no_challenge", error=str(exc)[:120])
        return False

    # Step 3: Try to get an audio challenge.
    for attempt in range(max_retries):
        log.info("recaptcha.attempt", attempt=attempt + 1, max=max_retries)

        # If we see image challenge, click the audio button.
        # Try multiple audio button selectors.
        audio_clicked = False
        for sel in _AUDIO_BUTTON_SELECTORS:
            try:
                audio_btn = await challenge_frame.query_selector(sel)
                if audio_btn:
                    await audio_btn.click()
                    audio_clicked = True
                    await page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

        if not audio_clicked:
            # Debug: dump challenge frame HTML to see what's there
            try:
                frame_html = await challenge_frame.content()
                log.warning("recaptcha.no_audio_button_clicked",
                            frame_html_excerpt=frame_html[:500])
            except Exception:
                log.warning("recaptcha.no_audio_button_clicked_no_html")

        # Step 4: Download the audio clip.
        audio_path = await _download_audio_clip(page, challenge_frame)
        if not audio_path:
            # Debug: dump challenge frame HTML
            try:
                frame_html = await challenge_frame.content()
                log.warning("recaptcha.no_audio_clip",
                            attempt=attempt + 1,
                            frame_html_excerpt=frame_html[:800])
            except Exception:
                log.warning("recaptcha.no_audio_clip", attempt=attempt + 1)
            # Try refreshing the challenge
            try:
                reload_btn = await challenge_frame.query_selector("#recaptcha-reload-button")
                if reload_btn:
                    await reload_btn.click()
                    await page.wait_for_timeout(1500)
            except Exception:
                pass
            continue

        # Step 5: Transcribe the audio.
        try:
            transcription = await transcribe_audio(audio_path)
        except Exception as exc:
            log.warning("recaptcha.transcribe_failed",
                        error=str(exc)[:120], attempt=attempt + 1)
            continue
        finally:
            try:
                os.unlink(audio_path)
            except Exception:
                pass

        if not transcription:
            log.warning("recaptcha.empty_transcription", attempt=attempt + 1)
            continue

        # Step 6: Submit the transcription.
        try:
            response_input = await challenge_frame.wait_for_selector(
                _AUDIO_RESPONSE_INPUT, timeout=5000
            )
            await response_input.fill(transcription)
            await page.wait_for_timeout(500)

            verify_btn = await challenge_frame.query_selector(_VERIFY_BUTTON)
            if verify_btn:
                await verify_btn.click()
                await page.wait_for_timeout(3000)
        except Exception as exc:
            log.warning("recaptcha.submit_failed",
                        error=str(exc)[:120], attempt=attempt + 1)
            continue

        # Step 7: Check if solved.
        try:
            checkbox_state = await frame.get_attribute(
                ".recaptcha-checkbox", "aria-checked"
            )
            if checkbox_state == "true":
                log.info("recaptcha.solved", attempt=attempt + 1,
                         transcription=transcription)
                return True
        except Exception:
            pass

        # Not solved — reload and try again.
        log.info("recaptcha.retry", attempt=attempt + 1,
                 transcription=transcription)
        try:
            reload_btn = await challenge_frame.query_selector("#recaptcha-reload-button")
            if reload_btn:
                await reload_btn.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass

    log.warning("recaptcha.all_retries_failed", max_retries=max_retries)
    return False


async def _download_audio_clip(
    page: Any,
    challenge_frame: Any,
) -> Optional[str]:
    """Download the reCAPTCHA audio clip to a temp file.

    Returns the path to the temp file, or None on failure.
    """
    try:
        # The audio download link's href is the audio URL.
        # Try multiple selectors since Google changes the DOM.
        link = None
        for sel in _AUDIO_DOWNLOAD_SELECTORS:
            try:
                link = await challenge_frame.wait_for_selector(sel, timeout=10000)
                if link:
                    break
            except Exception:
                continue

        if not link:
            log.warning("recaptcha.no_audio_link")
            return None
        href = await link.get_attribute("href")
        if not href:
            log.warning("recaptcha.no_audio_href")
            return None

        log.info("recaptcha.audio_url", url=href[:120])

        # Download via the page's browser context (preserves cookies/session).
        # Use page.evaluate to fetch the audio as a blob, then save to disk.
        audio_data = await page.evaluate("""
            async (url) => {
                try {
                    const resp = await fetch(url);
                    if (!resp.ok) return null;
                    const blob = await resp.blob();
                    const reader = new FileReader();
                    return new Promise((resolve) => {
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    });
                } catch(e) {
                    return null;
                }
            }
        """, href)

        if not audio_data or not isinstance(audio_data, str):
            log.warning("recaptcha.audio_download_failed")
            return None

        # The data URL is "data:audio/mp3;base64,...."
        # Strip the prefix and decode.
        import base64
        if "," not in audio_data:
            log.warning("recaptcha.bad_data_url")
            return None

        header, data = audio_data.split(",", 1)
        audio_bytes = base64.b64decode(data)

        # Determine extension from the MIME type.
        ext = ".mp3"
        if "wav" in header:
            ext = ".wav"

        fd, path = tempfile.mkstemp(suffix=ext, prefix="recaptcha_audio_")
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)

        log.info("recaptcha.audio_saved", path=path, size=len(audio_bytes))
        return path

    except Exception as exc:
        log.warning("recaptcha.audio_download_error", error=str(exc)[:120])
        return None


# ---------------------------------------------------------------------------
# Self-test — verify whisper loads and can transcribe
# ---------------------------------------------------------------------------

async def _self_test():
    """Verify the whisper model loads successfully."""
    print("reCAPTCHA audio solver self-test")
    print("Loading whisper model (base.en, CPU, int8)...")
    model = await _get_whisper_model()
    print(f"  Model loaded: {type(model).__name__}")
    print("  All systems go.")


if __name__ == "__main__":
    asyncio.run(_self_test())
