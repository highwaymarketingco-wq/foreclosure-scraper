"""Lexington County SC probate search — reCAPTCHA V2 audio solver via Groq Whisper.

www.lex-co.com/ProbateSearch/estates is an Angular SPA that renders reCAPTCHA V2
in explicit mode after page load. Without solving it the search endpoint returns
HTTP 401 / no results.

**IMPORTANT:** Headful mode required (headless=True gets blocked by Google anti-bot).
Run on VM only (DISPLAY=:99), NOT on Mac (user frustrated by local browsers).

Strategy:
1. Launch patchright (stealth Chromium) HEADFUL browser on VM.
2. Navigate to the probate search page; wait for Angular to boot and reCAPTCHA
   iframes to appear.
3. Click the reCAPTCHA checkbox — Google may auto-tick it (risk score low enough).
4. If not auto-solved, switch to audio challenge and solve via Groq Whisper STT
   (same technique proven live on businessfilings.sc.gov, 2026-10-12).
5. Once the token is in place, fill the date-range filter and click Search.
6. Parse the results table into Listing objects.

CAPTCHA solver re-verified against live page structure 2026-11-09.
Headless→headful fix verified 2026-11-24 (audio loads in headful, blocked in headless).
Groq API key read from GROQ_API_KEY env var or ~/.secrets/groq_api_key.txt.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://www.lex-co.com/ProbateSearch/estates"


# ---------------------------------------------------------------------------
# reCAPTCHA V2 audio solver (ported from sc_sos_entity.py / scripts/scsos_audio_solver.py)
# Proven live against businessfilings.sc.gov 2026-10-12; same Google reCAPTCHA
# infrastructure used here.
# ---------------------------------------------------------------------------

async def _get_recaptcha_response(page) -> str:
    """Return current g-recaptcha-response token, or empty string."""
    try:
        return await page.evaluate(
            "() => document.getElementById('g-recaptcha-response')?.value || ''"
        )
    except Exception:
        return ""


async def _speech_to_text_groq(audio_data: bytes) -> str | None:
    """Transcribe reCAPTCHA audio challenge via Groq Whisper API."""
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
        log.warning("lexington_probate.no_groq_key")
        return None

    content_type = "audio/wav" if audio_data[:4] == b"RIFF" else "audio/mpeg"
    files = {
        "file": ("audio.mp3", audio_data, content_type),
        "model": (None, "whisper-large-v3"),
        "language": (None, "en"),
        "response_format": (None, "json"),
        "temperature": (None, "0"),
        "prompt": (
            None,
            "A distorted robotic voice reads a sequence of numbers and single letters. "
            "Transcribe ONLY the numbers and letters, nothing else. Example: 7 3 9 2 5 1",
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                files=files,
            )
        if resp.status_code == 200:
            return resp.json().get("text", "")
        log.warning("lexington_probate.groq_error", status=resp.status_code)
        return None
    except Exception as exc:
        log.warning("lexington_probate.groq_exception", error=str(exc)[:120])
        return None


async def _find_challenge_frame(page):
    """Find the reCAPTCHA bframe (audio/visual challenge popup)."""
    for frame in page.frames:
        if "recaptcha/api2/bframe" in frame.url:
            return frame
    return None


async def _find_anchor_frame(page):
    """Find the reCAPTCHA anchor frame (the checkbox widget)."""
    for frame in page.frames:
        if "recaptcha/api2/anchor" in frame.url:
            return frame
    return None


async def _solve_audio_challenge(page, challenge_frame) -> bool:
    """Solve reCAPTCHA v2 using Claude vision API (visual challenge).

    NEW APPROACH (2026-11-24): Claude vision directly on the visual challenge,
    no audio button clicking. Audio transcription was broken (got "Shrinky Dink 
    Dinosaurs" instead of numbers).
    
    Returns True if the reCAPTCHA token is populated after verification.
    """
    from foreclosure_scraper.enrichment_recaptcha_visual_claude import solve_recaptcha_visual_claude
    
    # Take screenshot of the reCAPTCHA challenge
    # NOTE: Screenshot the page, not the frame (frames don't have screenshot method)
    try:
        screenshot_bytes = await page.screenshot(type="png")
    except Exception as exc:
        log.debug("lexington_probate.screenshot_failed", error=str(exc)[:80])
        return False
    
    # Solve with Claude vision
    answer = await solve_recaptcha_visual_claude(screenshot_bytes)
    if not answer:
        log.debug("lexington_probate.claude_vision_failed")
        return False
    
    log.info("lexington_probate.claude_answer", answer=answer[:20])

    # Type answer
    try:
        typed = await challenge_frame.evaluate("""(answer) => {
            const inp = document.getElementById('audio-response')
                     || document.querySelector('input[name="audio-response"]')
                     || document.querySelector('#response');
            if (!inp) return false;
            inp.value = answer;
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }""", answer)
        if not typed:
            return False
    except Exception as exc:
        log.debug("lexington_probate.type_error", error=str(exc)[:80])
        return False

    await asyncio.sleep(1.5)

    # Click verify
    try:
        await challenge_frame.evaluate("""() => {
            const btn = document.getElementById('recaptcha-verify-button')
                     || document.querySelector('.rc-button-default');
            if (btn) btn.click();
        }""")
    except Exception:
        pass

    # Check if solved
    await asyncio.sleep(2)
    try:
        resp_token = await page.evaluate("""() => {
            const r = document.getElementById('g-recaptcha-response');
            return r ? r.value : null;
        }""")
        if resp_token and len(resp_token) > 50:
            return True
        log.debug("lexington_probate.captcha_not_solved_after_verify")
        return False
    except Exception:
        return False


async def _do_captcha_flow(page, max_attempts: int = 8) -> bool:
    """Full reCAPTCHA V2 flow: checkbox click + visual challenge with Claude.

    Returns True when a valid token is in the page.
    """
    anchor = await _find_anchor_frame(page)
    if anchor:
        try:
            await anchor.click(".recaptcha-checkbox-border")
        except Exception:
            pass
        await asyncio.sleep(4)

    # Lucky path: checkbox was auto-solved (risk score low)
    if await _get_recaptcha_response(page):
        return True

    # Audio-solver loop
    for attempt in range(max_attempts):
        challenge = await _find_challenge_frame(page)
        if not challenge:
            # Challenge may have disappeared (auto-solved between iterations)
            if await _get_recaptcha_response(page):
                return True
            # Re-click checkbox to trigger the challenge popup
            anchor = await _find_anchor_frame(page)
            if anchor:
                try:
                    await anchor.click(".recaptcha-checkbox-border")
                    await asyncio.sleep(5)
                except Exception:
                    pass
            continue

        solved = await _solve_audio_challenge(page, challenge)
        if solved:
            return True

        # Reload the challenge for the next attempt
        if attempt < max_attempts - 1:
            ch2 = await _find_challenge_frame(page)
            if ch2:
                try:
                    await ch2.evaluate("""() => {
                        const btn = document.getElementById('recaptcha-reload-button')
                                 || document.querySelector('.rc-button-reload');
                        if (btn) btn.click();
                    }""")
                except Exception:
                    pass
            await asyncio.sleep(3)

    return False


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class LexingtonProbateScraper(BaseScraper):
    """Lexington County SC probate search — reCAPTCHA V2 audio solver."""

    slug = "counties_sc.lexington_probate"
    name = "Lexington SC Probate"
    category = "probate"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            try:
                from patchright.async_api import async_playwright
            except ImportError:
                from playwright.async_api import async_playwright
        except ImportError:
            log.error("lexington_probate.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # Changed 2026-11-24: headful mode works, headless blocked
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-gpu",
                ],
            )
            page = await browser.new_page()

            try:
                log.info("lexington_probate.loading", url=_URL)
                await page.goto(_URL, timeout=45000)

                # Angular SPA — wait for the app to boot (look for a recognisable
                # element that is only present after the JS framework has initialised).
                # Fall back to networkidle if no known selector appears.
                try:
                    await page.wait_for_selector(
                        "app-root, form, input, .g-recaptcha, iframe[src*='recaptcha']",
                        timeout=20000,
                    )
                except Exception:
                    await page.wait_for_load_state("networkidle", timeout=15000)

                # Give Angular + reCAPTCHA iframes time to fully mount
                await asyncio.sleep(5)

                log.info("lexington_probate.solving_captcha")
                solved = await _do_captcha_flow(page)

                if not solved:
                    log.warning("lexington_probate.captcha_unsolved")
                    # Partial: try parsing whatever the page rendered anyway
                    html = await page.content()
                    results.extend(self._parse_html(html))
                    await browser.close()
                    return results

                log.info("lexington_probate.captcha_solved_submitting_search")

                # Date range: last 365 days
                cutoff = (datetime.now() - timedelta(days=365))
                cutoff_str = cutoff.strftime("%m/%d/%Y")
                today_str = datetime.now().strftime("%m/%d/%Y")

                # Try to fill date fields (Angular forms use various selectors)
                for from_sel in [
                    "input[name*='from'], input[name*='start'], input[name*='begin']",
                    "#dateFrom, #fromDate, #startDate, #DateFrom",
                    "input[placeholder*='From'], input[placeholder*='from']",
                    "input[formcontrolname*='from'], input[formcontrolname*='start']",
                ]:
                    try:
                        el = await page.query_selector(from_sel)
                        if el:
                            await el.click(click_count=3)
                            await el.type(cutoff_str)
                            break
                    except Exception:
                        pass

                for to_sel in [
                    "input[name*='to'], input[name*='end']",
                    "#dateTo, #toDate, #endDate, #DateTo",
                    "input[placeholder*='To'], input[placeholder*='to']",
                    "input[formcontrolname*='to'], input[formcontrolname*='end']",
                ]:
                    try:
                        el = await page.query_selector(to_sel)
                        if el:
                            await el.click(click_count=3)
                            await el.type(today_str)
                            break
                    except Exception:
                        pass

                # Click search button
                clicked_search = False
                for btn_sel in [
                    "button:has-text('Search')",
                    "input[type='submit']",
                    "a:has-text('Search')",
                    "#btnSearch, #searchButton, #SearchButton",
                    "button[type='submit']",
                    "button:has-text('search')",
                ]:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn:
                            await btn.click()
                            clicked_search = True
                            break
                    except Exception:
                        pass

                if not clicked_search:
                    log.warning("lexington_probate.no_search_button")

                # Wait for results to render
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    await asyncio.sleep(5)

                html = await page.content()
                parsed = self._parse_html(html)
                results.extend(parsed)

                log.info("lexington_probate.done", found=len(results))

            except Exception as exc:
                log.warning("lexington_probate.error", error=str(exc)[:200])
            finally:
                await browser.close()

        return results

    def _parse_html(self, html: str) -> list[Listing]:
        """Parse probate estate results table into Listing objects."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select(
            "table tr, .results tr, .grid-view tr, .data-table tr, mat-row, .estate-row"
        )
        for row in rows[1:]:  # skip header
            cells = row.find_all(["td", "mat-cell"])
            if len(cells) < 3:
                continue

            case_num = cells[0].get_text(strip=True)
            decedent = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            filed_date = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            status = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            if not case_num or not decedent:
                continue

            results.append(Listing(
                source=self.slug,
                source_url=_URL,
                listing_type=ListingType.PROBATE_NOTICE,
                property_kind=PropertyKind.UNKNOWN,
                county="Lexington",
                state="SC",
                case_number=case_num,
                owner_name=decedent,
                raw={
                    "filed_date": filed_date,
                    "status": status,
                    "decedent": decedent,
                },
            ))

        return results
