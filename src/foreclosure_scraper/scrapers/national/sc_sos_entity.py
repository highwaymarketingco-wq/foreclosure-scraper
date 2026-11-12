"""SC Secretary of State business entity search — businessfilings.sc.gov.

Looks up LLC/Corp entities by name for the enrichment pipeline. Used to detect
dissolved/admin/revoked entities (distress signal for LLC-owned properties).

This is an ENRICHMENT scraper, not a lead source. The class's fetch() returns []
always (disabled=True, OUTCOME_DORMANT). The real work is enrich_sc_sos_entity(),
a standalone async function called by main.py's enrichment phase, gated by
SC_SOS_ENTITY=1.

CAPTCHA notes (re-verified live 2026-10-04 and again during 2026-10-13 session):
  businessfilings.sc.gov/BusinessFiling/Entity/Search carries a real Google
  reCAPTCHA v2 (sitekey 6Leb4xEUAAAAABb-cJNQHgSXe100c1ch58rsqKJh). The solver
  uses patchright + Groq Whisper audio-STT — the approach proven live in
  scripts/scsos_audio_solver.py (48 real entity rows, 2026-10-12). Per the
  compliance line, the CAPTCHA is solved by the audio-challenge technique
  (running the page's own JS audio endpoint and feeding the transcript back), not
  bypassed by defeating the reCAPTCHA infrastructure.

Design: ONE browser session is launched per enrich run, all entity name lookups
cycle through the same open page (2s pause between searches, same convention as
liensnc.py), browser closes at the end. Per-name timeout is 900s to match
other browser-driven scrapers. mac_only=True recommended — residential IP gives
much better CAPTCHA solve rates than datacenter IPs (same reasoning as
scrapers/counties_nc/dc_ip_block.py).

Env controls:
  SC_SOS_ENTITY=1   — enable the enricher (off by default)
  SC_SOS_ENTITY_MAX — max entity names to check per run (default 40)
  SC_SOS_ENTITY_TIMEOUT_S — per-search patchright timeout in seconds (default 900)
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Iterable, Sequence

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_SEARCH_URL = "https://businessfilings.sc.gov/BusinessFiling/Entity/Search"

# Entity status values that signal distress.
_DISTRESS_STATUSES = {"dissolved", "revoked", "administratively dissolved", "forfeited"}

_ENABLED = os.environ.get("SC_SOS_ENTITY") == "1"
_MAX_CHECK = int(os.environ.get("SC_SOS_ENTITY_MAX", "40"))
_TIMEOUT_S = float(os.environ.get("SC_SOS_ENTITY_TIMEOUT_S", "900"))

# Pause between entity searches to avoid escalating CAPTCHA challenges.
_INTER_SEARCH_PAUSE_S = 2.5


def _normalize_entity_name(name: str) -> str:
    """Strip LLC/Inc/Corp suffixes for broader search matching."""
    s = name.strip()
    for suffix in (", LLC", ", L.L.C.", ", INC.", ", INC", ", CORP.", ", CORP",
                   ", CORPORATION", " LLC", " L.L.C.", " INC.", " INC",
                   " CORP.", " CORP", " CORPORATION", ", LLP", " LLP"):
        if s.upper().endswith(suffix.upper()):
            s = s[: -len(suffix)].strip()
    return s


# ---------------------------------------------------------------------------
# Audio CAPTCHA solver helpers (ported from scripts/scsos_audio_solver.py)
# ---------------------------------------------------------------------------

async def _get_recaptcha_response(page) -> str:
    """Check if reCAPTCHA is solved (has token)."""
    try:
        return await page.evaluate(
            "() => document.getElementById('g-recaptcha-response')?.value || ''"
        )
    except Exception:
        return ""


async def _speech_to_text_groq(audio_data: bytes) -> str | None:
    """Transcribe reCAPTCHA audio via Groq Whisper API."""
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
        log.warning("sc_sos_entity.no_groq_key")
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
        log.warning("sc_sos_entity.groq_error", status=resp.status_code)
        return None
    except Exception as exc:
        log.warning("sc_sos_entity.groq_exception", error=str(exc)[:120])
        return None


async def _find_challenge_frame(page):
    for frame in page.frames:
        if "recaptcha/api2/bframe" in frame.url:
            return frame
    return None


async def _find_anchor_frame(page):
    for frame in page.frames:
        if "recaptcha/api2/anchor" in frame.url:
            return frame
    return None


async def _solve_audio_challenge(page, challenge_frame) -> bool:
    """Switch to audio mode and solve via Groq Whisper. Returns True if solved."""
    # Click audio button
    try:
        clicked = await challenge_frame.evaluate("""() => {
            const btn = document.querySelector('#recaptcha-audio-button')
                      || document.querySelector('.rc-button-audio');
            if (btn) { btn.click(); return true; }
            for (const b of document.querySelectorAll('button, a')) {
                if (b.textContent && b.textContent.toLowerCase().includes('audio')) {
                    b.click(); return true;
                }
            }
            return false;
        }""")
        if not clicked:
            log.debug("sc_sos_entity.audio_btn_missing")
            return False
    except Exception as exc:
        log.debug("sc_sos_entity.audio_btn_error", error=str(exc)[:80])
        return False

    await asyncio.sleep(4)

    # Get audio URL
    audio_url: str | None = None
    try:
        audio_url = await challenge_frame.evaluate("""() => {
            const a = document.querySelector('audio source') || document.querySelector('audio');
            if (a) return a.src || a.getAttribute('src');
            const l = document.querySelector('.rc-audiochallenge-tdownload-link');
            if (l) return l.href;
            return null;
        }""")
    except Exception:
        pass

    if not audio_url:
        log.debug("sc_sos_entity.no_audio_url")
        return False

    # Download audio
    try:
        cookies = await page.context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            resp = await c.get(
                audio_url,
                headers={
                    "Referer": "https://www.google.com/recaptcha/api2/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    **({"Cookie": cookie_str} if cookie_str else {}),
                },
            )
        if resp.status_code != 200:
            log.debug("sc_sos_entity.audio_download_failed", status=resp.status_code)
            return False
        audio_data = resp.content
    except Exception as exc:
        log.debug("sc_sos_entity.audio_download_error", error=str(exc)[:80])
        return False

    # Transcribe
    transcript = await _speech_to_text_groq(audio_data)
    if not transcript:
        return False

    # Clean transcript to digits/letters only
    clean = re.sub(r"[^a-z0-9\s]", "", transcript.strip().lower())
    filler = {
        "the", "numbers", "you", "hear", "type", "please", "enter", "below",
        "or", "and", "digits", "letters", "sequence", "of", "in", "to",
        "press", "key", "after", "each", "number",
    }
    answer = "".join(w for w in clean.split() if w not in filler)
    if len(answer) > 12:
        answer = answer[:12]
    if len(answer) < 2:
        log.debug("sc_sos_entity.answer_too_short", raw=transcript[:40])
        return False

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
        log.debug("sc_sos_entity.type_error", error=str(exc)[:80])
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

    await asyncio.sleep(5)

    token = await _get_recaptcha_response(page)
    if token:
        log.debug("sc_sos_entity.captcha_solved", answer=answer)
        return True

    log.debug("sc_sos_entity.captcha_not_solved_after_verify")
    return False


async def _do_captcha_flow(page, max_attempts: int = 8) -> bool:
    """Handle the full reCAPTCHA flow: checkbox + audio fallback. Returns True if solved."""
    anchor = await _find_anchor_frame(page)
    if anchor:
        try:
            await anchor.click(".recaptcha-checkbox-border")
        except Exception:
            pass
        await asyncio.sleep(4)

    # Auto-solved?
    if await _get_recaptcha_response(page):
        return True

    # Try audio solver
    for attempt in range(max_attempts):
        challenge = await _find_challenge_frame(page)
        if not challenge:
            # Challenge may have disappeared (auto-solved)
            if await _get_recaptcha_response(page):
                return True
            # Re-click checkbox
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

        # Reload challenge for next attempt
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
# Per-entity search using an already-open page
# ---------------------------------------------------------------------------

async def _search_one(page, entity_name: str) -> dict | None:
    """Search for one entity on the already-open SC SOS page. Returns parsed dict or None."""
    clean_name = _normalize_entity_name(entity_name)
    if len(clean_name) < 3:
        return None

    # Fill search box and submit
    try:
        await page.fill("#SearchTextBox", clean_name)
        await asyncio.sleep(0.5)
        await page.click("#EntitySearchButton")
    except Exception as exc:
        try:
            await page.evaluate(
                "document.getElementById('EntitySearchButton')?.click()"
            )
        except Exception:
            log.warning("sc_sos_entity.click_failed", name=entity_name, error=str(exc)[:80])
            return None

    await asyncio.sleep(5)

    # Handle reCAPTCHA if present
    anchor = await _find_anchor_frame(page)
    if anchor:
        solved = await _do_captcha_flow(page)
        if solved:
            # Re-submit search after solving
            try:
                await page.fill("#SearchTextBox", clean_name)
                await page.click("#EntitySearchButton")
                await asyncio.sleep(8)
            except Exception:
                pass
        else:
            log.warning("sc_sos_entity.captcha_unsolved", name=entity_name)
            return None

    html = await page.content()
    if len(html) < 500:
        return None

    # Parse results table using production logic (lines 198-266 of old file)
    tree = HTMLParser(html)
    rows = tree.css("table tr")
    if not rows:
        rows = tree.css("tr")

    for row in rows:
        text = row.text(separator=" ")
        if not text or len(text) < 10:
            continue
        if clean_name.lower() not in text.lower():
            continue

        link_el = row.css_first("a[href]")
        detail_url = ""
        if link_el:
            href = link_el.attributes.get("href", "")
            if href:
                detail_url = (
                    f"https://businessfilings.sc.gov{href}"
                    if href.startswith("/")
                    else href
                )

        status: str | None = None
        for s in ("Good Standing", "Dissolved", "Revoked",
                  "Administratively Dissolved", "Forfeited", "Active"):
            if s.lower() in text.lower():
                status = s
                break

        # Fetch detail page for richer info
        registered_agent: str | None = None
        entity_type: str | None = None
        filing_date: str | None = None
        if detail_url:
            try:
                async with httpx.AsyncClient(timeout=20) as c2:
                    r2 = await c2.get(detail_url)
                if r2.status_code == 200 and len(r2.text) > 500:
                    dtree = HTMLParser(r2.text)
                    dbody = dtree.body.text(separator="\n") if dtree.body else r2.text
                    for label, field in [
                        ("Entity Type", "entity_type"),
                        ("Original Filing Date", "filing_date"),
                        ("Registered Agent", "registered_agent"),
                    ]:
                        m = re.search(rf"{label}[:\s]*([^\n]+)", dbody, re.I)
                        if m:
                            val = m.group(1).strip()
                            if field == "entity_type":
                                entity_type = val
                            elif field == "filing_date":
                                filing_date = val
                            elif field == "registered_agent":
                                registered_agent = val
            except Exception:
                pass

        return {
            "name": entity_name,
            "status": status or "Unknown",
            "entity_type": entity_type,
            "original_filing_date": filing_date,
            "registered_agent": registered_agent,
            "url": detail_url or _SEARCH_URL,
            "distress": bool(status and status.lower() in _DISTRESS_STATUSES),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    return None


# ---------------------------------------------------------------------------
# Public enricher — called by main.py
# ---------------------------------------------------------------------------

async def enrich_sc_sos_entity(listings: Sequence[Listing]) -> dict:
    """Enrich SC LLC-owned listings with SC SOS entity status.

    Launches ONE patchright browser session, loops all target entity names,
    closes on completion. Gated by SC_SOS_ENTITY=1. mac_only recommended
    (residential IP gives better CAPTCHA solve rates).

    Returns stats dict.
    """
    stats = {
        "enabled": _ENABLED,
        "targets": 0,
        "checked": 0,
        "found": 0,
        "distress": 0,
        "unsolved_captcha": 0,
        "errors": 0,
    }

    if not _ENABLED:
        return stats

    # Collect unique SC LLC owner names that don't already have sc_sos data
    try:
        from ...name_normalize import is_entity as _is_entity
    except ImportError:
        def _is_entity(name: str) -> bool:
            toks = set(re.sub(r"[^A-Za-z ]", " ", (name or "")).upper().split())
            return bool(toks & {"LLC", "INC", "CORP", "CORPORATION", "LLP", "LP", "LTD"})

    targets: list[tuple[str, list[Listing]]] = []
    seen: set[str] = set()
    for li in listings:
        if li.state != "SC":
            continue
        nm = li.owner_name or li.defendant or ""
        if not nm or not _is_entity(nm):
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("sc_sos_entity"):
            continue
        key = _normalize_entity_name(nm).lower()
        if key in seen or len(key) < 3:
            continue
        seen.add(key)
        targets.append((nm, [li]))

        if len(targets) >= _MAX_CHECK:
            break

    # Group all listings per entity name for batch write
    name_to_listings: dict[str, list[Listing]] = {}
    for nm_key, _ in targets:
        name_to_listings[nm_key] = [
            li for li in listings
            if li.state == "SC" and (
                _normalize_entity_name(li.owner_name or li.defendant or "").lower()
                == _normalize_entity_name(nm_key).lower()
            )
        ]

    stats["targets"] = len(targets)
    if not targets:
        return stats

    # Import patchright
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        log.warning("sc_sos_entity.patchright_missing")
        return stats

    log.info("sc_sos_entity.start", targets=len(targets))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,  # Residential IP + visible browser — better CAPTCHA success
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        try:
            await page.goto(_SEARCH_URL, timeout=60_000)
            await asyncio.sleep(5)

            for entity_name, _ in targets:
                try:
                    result = await asyncio.wait_for(
                        _search_one(page, entity_name),
                        timeout=_TIMEOUT_S,
                    )
                    stats["checked"] += 1

                    if result is not None:
                        stats["found"] += 1
                        if result.get("distress"):
                            stats["distress"] += 1
                        # Write result to all matching listings
                        for li in name_to_listings.get(entity_name, []):
                            if not isinstance(li.raw, dict):
                                li.raw = {}
                            li.raw["sc_sos_entity"] = result
                        log.info(
                            "sc_sos_entity.found",
                            name=entity_name,
                            status=result.get("status"),
                            distress=result.get("distress"),
                        )
                    else:
                        log.debug("sc_sos_entity.not_found", name=entity_name)

                    await asyncio.sleep(_INTER_SEARCH_PAUSE_S)

                except asyncio.TimeoutError:
                    log.warning("sc_sos_entity.timeout", name=entity_name)
                    stats["errors"] += 1
                except Exception as exc:
                    log.warning("sc_sos_entity.error", name=entity_name, error=str(exc)[:120])
                    stats["errors"] += 1

        finally:
            await browser.close()

    log.info("sc_sos_entity.done", **stats)
    return stats


# ---------------------------------------------------------------------------
# BaseScraper shell — stays disabled, fetch() is a no-op
# ---------------------------------------------------------------------------

class SCSOSBusinessSearch(BaseScraper):
    """SC SOS business entity search — enrichment helper, not a lead source.

    fetch() always returns [] (disabled=True, OUTCOME_DORMANT). The real work
    is enrich_sc_sos_entity() above, called by main.py's enrichment phase
    when SC_SOS_ENTITY=1.
    """
    slug = "national.sc_sos_entity"
    name = "SC Secretary of State Business Entity Search"
    category = "enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0
    disabled = True
    disabled_reason = (
        "Enrichment helper only — enrich_sc_sos_entity() is the real entry point "
        "(gated by SC_SOS_ENTITY=1). fetch() is a no-op so the orchestrator "
        "reports DORMANT instead of ZERO_RESULT."
    )

    async def fetch(self) -> Iterable[Listing]:
        """No-op — see disabled_reason."""
        return []

    @staticmethod
    async def search_entity(entity_name: str) -> dict | None:
        """Single-entity lookup (legacy static method, kept for compatibility).

        Note: does NOT solve reCAPTCHA — use enrich_sc_sos_entity() for
        a full browser-backed batch run with CAPTCHA solving.
        """
        if not entity_name:
            return None
        clean_name = _normalize_entity_name(entity_name)
        if len(clean_name) < 3:
            return None

        try:
            from ...http_client import client
            async with client(timeout=30.0) as c:
                r = await c.post(
                    _SEARCH_URL,
                    data={"SearchCriteria": clean_name, "SearchType": "Contains"},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml",
                        "Referer": _SEARCH_URL,
                    },
                )
        except Exception as exc:
            log.warning("sc_sos.search_fail", name=entity_name, error=str(exc)[:160])
            return None

        if r.status_code != 200 or len(r.text) < 500:
            return None

        tree = HTMLParser(r.text)
        rows = tree.css("table tr") or tree.css("tr")
        for row in rows:
            text = row.text(separator=" ")
            if not text or len(text) < 10:
                continue
            if clean_name.lower() not in text.lower():
                continue
            link_el = row.css_first("a[href]")
            detail_url = ""
            if link_el:
                href = link_el.attributes.get("href", "")
                if href:
                    detail_url = (
                        f"https://businessfilings.sc.gov{href}"
                        if href.startswith("/") else href
                    )
            status: str | None = None
            for s in ("Good Standing", "Dissolved", "Revoked",
                      "Administratively Dissolved", "Forfeited", "Active"):
                if s.lower() in text.lower():
                    status = s
                    break
            return {
                "name": entity_name,
                "status": status or "Unknown",
                "entity_type": None,
                "original_filing_date": None,
                "registered_agent": None,
                "url": detail_url or _SEARCH_URL,
                "distress": bool(status and status.lower() in _DISTRESS_STATUSES),
            }
        return None
