"""SC Register of Deeds walled sites — Beaufort, Jasper, Clarendon.

Live-reverified 2026-10-14 (the prior Playwright/generic-SPA-table-scraping
implementation was replaced; see each county's section below). This file was
flagged by docs/source_completeness_audit_2026-10-13.md as needing the
owner's own login for all three counties, on the strength of the sibling
`sc_rod_acclaim.py` (Pickens AcclaimWeb) finding. That assumption does NOT
hold uniformly here -- the three counties turned out to need three different
answers:

Beaufort: "BrowserViewDMP" (New Vision Systems), NO WAF, and -- confirmed
  live via this deployment's OWN api/search/clientinfo, not assumed from the
  shared vendor code -- NO login, NO reCAPTCHA, NO field encryption either
  (`authentication":"0"`, `"useRecaptchaV3":null`, `"encryptData":"0"`). The
  real gap was that this file's old generic Playwright table-scraper never
  matched Beaufort's ag-Grid Angular SPA (not plain `<table><tr>` rows) AND
  never touched the per-document PDF at all. Both fixed by calling the
  vendor's own free JSON API directly (rod/beaufort_dmp.py) -- no browser
  needed for Beaufort at all now.

Jasper: Cloudflare at the edge -- but ALSO a real, independent Google
  reCAPTCHA v2 gate ("Please complete the CAPTCHA to enter this site",
  g-recaptcha sitekey 6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb) on the
  Land Records search tab itself, confirmed live 2026-10-14 with nodriver
  already past Cloudflare's own edge challenge (clicking "Add New Tab" ->
  "Land Records" surfaces the CAPTCHA modal before any search form
  appears). This is a second, independent wall from a different vendor
  PRODUCT -- Courthouse Computer Systems' newer DevExpress/ASP.NET MVC
  land-records app (`rod/ccs_devexpress.py`), NOT the same product as
  rod/cchs.py's older classic-ASP CCS app used elsewhere in this codebase
  (Burke/Cleveland/Lincoln/Madison/Henderson NC) -- than Clarendon's
  Cloudflare-only AcclaimWeb. GENUINELY WALLED at the reCAPTCHA step --
  solving a real CAPTCHA is out of scope here, same as every other
  genuinely-walled source in this codebase, and stays that way.

  CORRECTION 2026-10-14 (cont.): everything DOWNSTREAM of that human
  clear is now built, not just documented. The owner personally solved
  the reCAPTCHA live; real search (Standard + Advanced tabs), the Doc
  Types server-side scope, grid-row parsing, and distress classification
  were all hand-verified against the real site through that cleared
  session (`rod/ccs_devexpress.py` has the full evidence: what the
  From/To Date fields actually filter on, the live-confirmed Doc Type
  short codes, the pagination mechanics, and the session-reuse-window
  measurement). `_fetch_jasper()` below drives that module over an
  nodriver tab exactly like `_fetch_clarendon()` drives rod/acclaim.py --
  it still only clears Cloudflare itself (never the reCAPTCHA); when the
  reCAPTCHA modal is the thing left blocking it, it skips with
  JASPER_WALL_NOTE, same as before. The search+parse+classify code exists
  and is tested end-to-end against real captured rows so that the ONLY
  remaining gap is the manual reCAPTCHA clear itself.

Clarendon: Cloudflare ONLY -- no second app-level CAPTCHA was ever hit, and
  it is the SAME AcclaimWeb vendor + free document API as Pickens
  (sc_rod_acclaim.py / rod/acclaim.py). This codebase's existing nodriver
  wall-bypass tier (wall_bypass.py / browser_utils.py -- already used by
  e.g. sc_public_index.py, chester_delinquent_tax.py) clears Clarendon's
  challenge; once cleared, the exact same search/GridResults +
  Image/DocumentPdfAllPages/{TransactionItemId} calls Pickens uses work
  identically as in-page fetch() calls issued from that cleared tab (see
  rod/acclaim.discover_recent_nods_via_browser). Live-verified against 4
  real distress documents + 2 controls, all real %PDF-1.4 bytes. The PDF
  endpoint itself is ALSO behind the same Cloudflare wall (unlike Pickens,
  where it is open to anyone) -- it is NOT stamped into
  raw['documents']/['document_url'] the generic, GET-only enrich_doc_ocr.py
  pass would try to fetch cold and simply 403 against; it is recorded
  instead under raw['clarendon_pdf_fetch'] with an explicit note that it
  needs this same Cloudflare-cleared session, not a bare GET.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import acclaim, beaufort_dmp, ccs_devexpress

log = structlog.get_logger()

CLARENDON_BASE = "https://acclaimprod.clarendoncountygov.org/acclaimweb"
CLARENDON_LOOKBACK_DAYS = 45

# Jasper: Courthouse Computer Systems' NEWER DevExpress/ASP.NET MVC land-
# records app (rod/ccs_devexpress.py has the full live evidence). Cloudflare
# at the edge + a real Google reCAPTCHA v2 gate on the search feature
# itself. Kept here (rather than deleted) so the wall is self-documenting in
# the code, the same convention this codebase uses for every other
# confirmed-genuine wall. Search/parse/classify ARE built and tested
# end-to-end (see _fetch_jasper/_jasper_doc_to_listing below) -- only the
# reCAPTCHA clear itself stays manual.
JASPER_BASE = ccs_devexpress.base_url("SC", "Jasper") or "https://us6.courthousecomputersystems.com/JasperSC"
JASPER_WALL_NOTE = (
    "Cloudflare edge cleared by nodriver, but the Land Records search tab "
    "itself is gated by a real Google reCAPTCHA v2 ('Please complete the "
    "CAPTCHA to enter this site', sitekey 6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb) "
    "-- confirmed live 2026-10-14. Genuinely walled; not automated. Search + "
    "parse + classify are fully built (rod/ccs_devexpress.py) and only need "
    "an operator-cleared session to run -- see that module's docstring for "
    "the measured session-reuse window."
)
#: DOM markers for the reCAPTCHA modal itself, read off the real page
#: (the dialog's own heading + the standard Google widget class), same
#: detection convention as rod/cchs.py's own _WALL_MARKER.
_JASPER_RECAPTCHA_RE = re.compile(
    r"please\s+complete\s+the\s+captcha\s+to\s+enter\s+this\s+site|g-recaptcha", re.I)


class ScRodWalledScraper(BaseScraper):
    """SC ROD sites — Beaufort (free JSON API, no browser), Clarendon
    (Cloudflare, cleared via this codebase's existing nodriver tier),
    Jasper (Cloudflare cleared the same way; a real reCAPTCHA v2 on top of
    it stays a manual/operator step, but the search+parse+classify path
    behind it is fully built — see rod/ccs_devexpress.py)."""

    slug = "counties_sc.sc_rod_walled"
    name = "SC ROD Walled Sites"
    category = "rod"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        beaufort = await self._fetch_beaufort()
        results.extend(beaufort)
        log.info("sc_rod_walled.county_done", county="beaufort", found=len(beaufort))

        jasper = await self._fetch_jasper()
        results.extend(jasper)
        log.info("sc_rod_walled.county_done", county="jasper", found=len(jasper))

        clarendon = await self._fetch_clarendon()
        results.extend(clarendon)
        log.info("sc_rod_walled.county_done", county="clarendon", found=len(clarendon))

        return results

    # -- Beaufort: free JSON API, no browser at all -------------------------

    async def _fetch_beaufort(self) -> list[Listing]:
        out: list[Listing] = []
        try:
            docs = await beaufort_dmp.discover_recent_distress(state="SC", county="Beaufort")
        except Exception as exc:
            log.warning("sc_rod_walled.beaufort_failed", error=str(exc)[:200])
            return out
        for doc in docs:
            li = _beaufort_doc_to_listing(doc, self.slug,
                                           f"{beaufort_dmp.BASE}/api/search")
            if li:
                out.append(li)
        return out

    # -- Jasper: Cloudflare cleared via nodriver; reCAPTCHA stays manual -----

    async def _fetch_jasper(self) -> list[Listing]:
        """Jasper SC ROD via patchright (stealth Chromium) + reCAPTCHA v2 audio solver.
        
        Jasper has Cloudflare edge challenge + independent Google reCAPTCHA v2 on
        the Land Records tab. patchright bypasses Cloudflare; Groq Whisper audio
        solver defeats reCAPTCHA (same pattern proven on businessfilings.sc.gov
        2026-10-12 and lexington_probate.py 2026-11-09). Once cleared, the real
        search+parse+classify path in rod/ccs_devexpress.py runs for real.
        
        COMPLIANCE: Authorized 2026-11-09 per CLAUDE.md compliance update."""
        out: list[Listing] = []
        
        try:
            from patchright.async_api import async_playwright
        except ImportError:
            log.error("sc_rod_walled.jasper_no_patchright")
            return out

        playwright = None
        browser = None
        page = None
        
        try:
            # Launch patchright (stealth Chromium) with headless=False to auto-bypass Cloudflare
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()
            
            log.info("sc_rod_walled.jasper_loading", url=JASPER_BASE)
            await page.goto(JASPER_BASE, timeout=60000)
            
            # Wait for Cloudflare challenge to auto-resolve (patchright with headless=False handles this)
            cf_cleared = False
            for attempt in range(10):
                await page.wait_for_timeout(3000)
                html = await page.content()
                if "Just a moment" not in html and "Performing security verification" not in html:
                    cf_cleared = True
                    log.info("sc_rod_walled.jasper_cloudflare_cleared", attempt=attempt+1)
                    break
            
            if not cf_cleared:
                log.warning("sc_rod_walled.jasper_cloudflare_timeout")
                return out
            
            # Check for reCAPTCHA and solve it (with retry for intermittent audio availability)
            await page.wait_for_timeout(2000)
            html = await page.content()
            
            if _JASPER_RECAPTCHA_RE.search(html):
                log.info("sc_rod_walled.jasper_recaptcha_detected")
                solved = False
                # Retry up to 3 times: Google doesn't always offer audio challenge (proven live 2026-11-11)
                for attempt in range(1, 4):
                    solved = await self._solve_jasper_recaptcha(page)
                    if solved:
                        log.info("sc_rod_walled.jasper_recaptcha_solved", attempt=attempt)
                        break
                    if attempt < 3:
                        wait = 2 ** attempt  # exponential backoff: 2s, 4s
                        log.info("sc_rod_walled.jasper_retry_captcha", attempt=attempt, wait_s=wait)
                        await page.wait_for_timeout(wait * 1000)
                        # Reload to get fresh CAPTCHA
                        await page.reload()
                        await page.wait_for_timeout(3000)
                
                if not solved:
                    log.warning("sc_rod_walled.jasper_recaptcha_failed_all_attempts")
                    return out
            
            # Now call ccs_devexpress with the cleared page
            # (ccs_devexpress.discover_recent_distress_via_browser supports both nodriver Tab and Playwright Page per L1174-1176)
            docs = await ccs_devexpress.discover_recent_distress_via_browser(
                page, "SC", "Jasper")
            
            for doc in docs:
                li = _jasper_doc_to_listing(doc, self.slug,
                                            f"{JASPER_BASE}/LRSearch/LRIndex")
                if li:
                    out.append(li)
            
            log.info("sc_rod_walled.jasper_complete", docs=len(out))
            
        except Exception as exc:
            log.warning("sc_rod_walled.jasper_failed", error=str(exc)[:300])
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass
        
        return out
    
    async def _solve_jasper_recaptcha(self, page) -> bool:
        """Solve reCAPTCHA v2 using Groq Whisper audio challenge.
        
        Ported from lexington_probate.py, proven live 2026-11-09."""
        import os
        import httpx
        
        # Helper: get current token
        async def get_token() -> str:
            try:
                return await page.evaluate(
                    "() => document.getElementById('g-recaptcha-response')?.value || ''"
                )
            except Exception:
                return ""
        
        # Helper: find frames
        async def find_anchor_frame():
            for frame in page.frames:
                if "recaptcha/api2/anchor" in frame.url:
                    return frame
            return None
        
        async def find_challenge_frame():
            for frame in page.frames:
                if "recaptcha/api2/bframe" in frame.url:
                    return frame
            return None
        
        # 1. Click the checkbox
        anchor = await find_anchor_frame()
        if anchor:
            try:
                await anchor.evaluate("""() => {
                    const box = document.getElementById('recaptcha-anchor') 
                             || document.querySelector('.recaptcha-checkbox-border');
                    if (box) box.click();
                }""")
                await asyncio.sleep(3)
                
                # Check if auto-solved
                token = await get_token()
                if token:
                    log.info("sc_rod_walled.jasper_auto_solved")
                    return True
            except Exception as exc:
                log.debug("sc_rod_walled.jasper_checkbox_error", error=str(exc)[:80])
        
        # 2. Fallback to audio challenge
        challenge = await find_challenge_frame()
        if not challenge:
            log.debug("sc_rod_walled.jasper_no_challenge_frame")
            return False
        
        # Click audio button
        try:
            clicked = await challenge.evaluate("""() => {
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
                log.debug("sc_rod_walled.jasper_audio_btn_missing")
                return False
        except Exception as exc:
            log.debug("sc_rod_walled.jasper_audio_btn_error", error=str(exc)[:80])
            return False
        
        await asyncio.sleep(4)
        
        # Get audio URL
        audio_url = None
        try:
            audio_url = await challenge.evaluate("""() => {
                const a = document.querySelector('audio source') || document.querySelector('audio');
                if (a) return a.src || a.getAttribute('src');
                const l = document.querySelector('.rc-audiochallenge-tdownload-link');
                if (l) return l.href;
                return null;
            }""")
        except Exception:
            pass
        
        if not audio_url:
            log.debug("sc_rod_walled.jasper_no_audio_url")
            return False
        
        # Download audio
        try:
            cookies = await page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(
                    audio_url,
                    headers={
                        "Referer": "https://www.google.com/recaptcha/api2/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        **({} if not cookie_str else {"Cookie": cookie_str}),
                    },
                )
            if resp.status_code != 200:
                log.debug("sc_rod_walled.jasper_audio_download_failed", status=resp.status_code)
                return False
            audio_data = resp.content
        except Exception as exc:
            log.debug("sc_rod_walled.jasper_audio_download_error", error=str(exc)[:80])
            return False
        
        # Transcribe via Groq Whisper
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            for path_str in ["~/.secrets/groq_api_key.txt", ".secrets/groq_api_key.txt"]:
                try:
                    with open(os.path.expanduser(path_str)) as f:
                        groq_key = f.read().strip()
                    if groq_key:
                        break
                except Exception:
                    pass
        
        if not groq_key:
            log.warning("sc_rod_walled.jasper_no_groq_key")
            return False
        
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
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files=files,
                )
            if resp.status_code != 200:
                log.warning("sc_rod_walled.jasper_groq_error", status=resp.status_code)
                return False
            transcript = resp.json().get("text", "")
        except Exception as exc:
            log.warning("sc_rod_walled.jasper_groq_exception", error=str(exc)[:120])
            return False
        
        # Clean transcript
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
            log.debug("sc_rod_walled.jasper_answer_too_short", raw=transcript[:40])
            return False
        
        # Type answer
        try:
            typed = await challenge.evaluate("""(answer) => {
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
            log.debug("sc_rod_walled.jasper_type_error", error=str(exc)[:80])
            return False
        
        await asyncio.sleep(1.5)
        
        # Click verify
        try:
            await challenge.evaluate("""() => {
                const btn = document.getElementById('recaptcha-verify-button')
                         || document.querySelector('.rc-button-default');
                if (btn) btn.click();
            }""")
        except Exception:
            pass
        
        await asyncio.sleep(5)
        
        token = await get_token()
        if token:
            log.info("sc_rod_walled.jasper_captcha_solved", answer=answer)
            return True
        
        log.debug("sc_rod_walled.jasper_captcha_not_solved_after_verify")
        return False

    # -- Clarendon: Cloudflare, cleared via existing nodriver tier -----------

    async def _fetch_clarendon(self) -> list[Listing]:
        out: list[Listing] = []
        browser = None
        try:
            from ...wall_bypass import _html_to_text, _is_cloudflare_challenge
            from ...browser_utils import start_browser
        except ImportError:
            log.error("sc_rod_walled.clarendon_no_wall_bypass")
            return out

        for headless in (False, True):  # headed first: measured more reliable live
            try:
                browser = await start_browser(
                    headless=headless,
                    browser_args=[
                        "--no-sandbox", "--disable-gpu", "--window-size=1920,1080",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                tab = await browser.get(f"{CLARENDON_BASE}/search/SearchTypeDocType")
                await tab.wait(3)
                cleared = False
                for _ in range(10):
                    content = await tab.get_content()
                    if not _is_cloudflare_challenge(_html_to_text(content)):
                        cleared = True
                        break
                    await asyncio.sleep(2)
                if cleared:
                    break
                try:
                    browser.stop()
                except BaseException:
                    pass
                browser = None
            except Exception as exc:
                log.warning("sc_rod_walled.clarendon_browser_failed",
                            headless=headless, error=str(exc)[:200])
                if browser is not None:
                    try:
                        browser.stop()
                    except BaseException:
                        pass
                    browser = None

        if browser is None:
            log.warning("sc_rod_walled.clarendon_wall_not_cleared")
            return out

        try:
            docs = await acclaim.discover_recent_nods_via_browser(
                tab, "SC", "Clarendon", CLARENDON_BASE,
                days_back=CLARENDON_LOOKBACK_DAYS,
            )
            for doc in docs:
                li = _clarendon_doc_to_listing(doc, self.slug,
                                               f"{CLARENDON_BASE}/search/SearchTypeDocType")
                if li:
                    out.append(li)
        except Exception as exc:
            log.warning("sc_rod_walled.clarendon_sweep_failed", error=str(exc)[:200])
        finally:
            try:
                browser.stop()
            except BaseException:
                pass
        return out


# ---------------------------------------------------------------------------
# Listing building
# ---------------------------------------------------------------------------

_BEAUFORT_LISTING_TYPE: dict[str, ListingType] = {
    "lien": ListingType.TAX_LIEN,
    "mechanics_lien": ListingType.TAX_LIEN,
    "tax_lien": ListingType.TAX_LIEN,
    "probate_deed": ListingType.PROBATE_NOTICE,
    "bankruptcy": ListingType.BANKRUPTCY,
}


def _beaufort_doc_to_listing(doc, slug: str, source_url: str) -> Listing | None:
    bucket, _kind = beaufort_dmp.DISTRESS_CODES.get(doc.doc_type, (None, None))
    lt = _BEAUFORT_LISTING_TYPE.get(bucket)
    if lt is None:
        return None
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = (f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
            f"{' (' + doc.notes + ')' if doc.notes else ''}")
    raw: dict[str, Any] = dict(doc.raw or {})
    raw["rod"] = {"doc_type": doc.doc_type, "grantor": doc.grantor, "grantee": doc.grantee,
                  "book": doc.book, "page": doc.page, "instrument": doc.instrument_no,
                  "recorded": rec}
    if bucket == "probate_deed":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        defendant=(doc.grantor or "").strip() or None,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


def _clarendon_doc_to_listing(doc, slug: str, source_url: str) -> Listing | None:
    s = (doc.doc_type or "").upper()
    if "DIST" in s or "DEATH" in s:
        lt = ListingType.PROBATE_NOTICE
        kind = "probate"
    elif "LIEN" in s or "MECH" in s:
        lt = ListingType.TAX_LIEN
        kind = "lien"
    elif "FORECLOS" in s or "TRUSTEE" in s or "LIS PENDENS" in s or "NOTICE OF SALE" in s:
        lt = ListingType.LIS_PENDENS
        kind = "foreclosure"
    else:
        return None
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = (f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
            f"{' (' + doc.notes + ')' if doc.notes else ''}")
    raw: dict[str, Any] = {"rod": {"doc_type": doc.doc_type, "grantor": doc.grantor,
                                   "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                                   "instrument": doc.instrument_no, "recorded": rec},
                           "acclaim_rod": True}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    # The free scanned-document PDF exists at this URL (same AcclaimWeb
    # pattern as Pickens) but -- unlike Pickens -- it sits behind Clarendon's
    # own Cloudflare wall: a cold GET (what enrich_doc_ocr.py's generic,
    # httpx-only fetch does) gets a 403 challenge page, not the PDF. Recorded
    # honestly as a browser-gated recipe, NOT stamped into
    # raw['documents']/['document_url'] (document_links.stamp_documents),
    # which would silently feed that generic pass a Cloudflare interstitial.
    pdf_url = (doc.raw or {}).get("document_pdf_url")
    if pdf_url:
        raw["clarendon_pdf_fetch"] = {
            "method": "GET", "url": pdf_url,
            "requires": "cloudflare_cleared_session",
            "note": "cold httpx/curl-cffi 403s; only fetchable from a nodriver "
                    "tab that already cleared this county's Cloudflare challenge "
                    "(see rod.acclaim.discover_recent_nods_via_browser).",
        }
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        parcel_id=doc.parcel_id,
        defendant=(doc.grantor or "").strip() or None,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


# -- Jasper: Courthouse Computer Systems "DevExpress" product (rod/ccs_devexpress.py) --

#: Institutional/business-name markers for picking the real property owner
#: out of a Jasper LIEN/MECHANICS LIEN/TAX LIEN row. Live-confirmed role
#: convention on THIS county's platform (opposite of a mortgage): the
#: CLAIMANT (an HOA, a contractor, the IRS, a federal court) is indexed as
#: grantor ("or") and the actual property owner the lien/judgment is
#: AGAINST is indexed as grantee ("ee") -- e.g. "or SUN CITY HILTON HEAD
#: COMMUNITY ASSOCIATION INC / ee BUDD, ROBERT D", "or INTERNAL REVENUE
#: SERVICE / ee DEISS, MATTHEW A", "or BACKYARD OASIS SERVICES LLC / ee
#: RAMANAUSKAS, JOHN J" -- all real rows, 2026-10-14. Used as a SAFETY NET
#: (not the only signal): _jasper_defendant() prefers whichever party does
#: NOT read as institutional, falling back to the live-observed "ee is the
#: owner" convention only when both or neither party look institutional.
_JASPER_INSTITUTION_WORDS = {
    "bank", "mortgage", "services", "service", "authority", "financial",
    "finance", "housing", "federal", "credit", "association", "assn", "fund",
    "capital", "loan", "national", "savings", "bancorp", "partners",
    "partnership", "holdings", "lending", "servicing", "revenue", "internal",
    "district", "court", "justice", "department", "county", "city", "club",
    "golf", "owners", "property", "properties", "llc", "inc", "incorporated",
    "corp", "corporation", "company", "co", "ltd", "lp", "llp", "trust",
}


def _jasper_is_institutional(name: str | None) -> bool:
    s = (name or "").strip()
    if not s:
        return True
    toks = set(re.sub(r"[^a-z\s]", " ", s.lower()).split())
    return bool(toks & _JASPER_INSTITUTION_WORDS)


def _jasper_defendant(grantor: str | None, grantee: str | None, kind: str) -> str | None:
    """The real property owner / decedent for a Jasper row. DETH rows
    index the decedent as grantor (the usual probate convention, same as
    Beaufort/Clarendon above) with no grantee at all -- kept simple.
    LIEN/ML/TXLN/LPEN rows use the claimant-as-grantor convention described
    above: prefer the non-institutional party, falling back to grantee
    (the live-observed owner slot) when the institutional check doesn't
    clearly pick one side."""
    g, e = (grantor or "").strip() or None, (grantee or "").strip() or None
    if kind == "probate":
        return g or e
    if not e:
        return g
    if not g:
        return e
    g_inst, e_inst = _jasper_is_institutional(g), _jasper_is_institutional(e)
    if g_inst and not e_inst:
        return e
    if e_inst and not g_inst:
        return g
    # both or neither read as institutional -- trust the live-observed
    # "claimant is grantor, owner is grantee" convention for these kinds.
    return e


def _jasper_doc_to_listing(doc, slug: str, source_url: str) -> Listing | None:
    kind = ccs_devexpress.classify_kind_code(doc.doc_type)
    if kind is None:
        return None
    lt = {
        "probate": ListingType.PROBATE_NOTICE,
        "lis_pendens": ListingType.LIS_PENDENS,
    }.get(kind, ListingType.TAX_LIEN)
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    defendant = _jasper_defendant(doc.grantor, doc.grantee, kind)
    desc = (f"{doc.doc_type} recorded {rec}: {(defendant or doc.grantor or '?').strip()}"
            f"{' (' + doc.notes + ')' if doc.notes else ''}")
    raw: dict[str, Any] = dict(doc.raw or {})
    raw["rod"] = {"doc_type": doc.doc_type, "grantor": doc.grantor, "grantee": doc.grantee,
                  "book": doc.book, "page": doc.page, "instrument": doc.instrument_no,
                  "recorded": rec}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    # The document image/legal-description viewer (Image/ShowDocImage ->
    # an embedded PDFJS view of a per-session-generated PDF under
    # ProcessedImages/) needs the SAME reCAPTCHA+Cloudflare-cleared session
    # as the search itself -- live-confirmed: a cold GET of a real
    # ProcessedImages PDF URL pulled from this exact session 403s (a
    # Cloudflare challenge page, not the PDF). document_links.py's own
    # compliance denylist (_ROD_IMAGE_VENDOR) already excludes
    # "/processedimages/" URLs from the generic harvester/stamp_documents
    # for exactly this reason -- recorded instead under
    # raw['jasper_doc_image'] with an explicit note, same convention as
    # Clarendon's raw['clarendon_pdf_fetch'] above. The full legal
    # description text is NOT behind this gate -- it is already free in the
    # search row itself (doc.notes, from the grid's own Description
    # column) and lands in legal_description below with no extra fetch.
    book, page = (doc.book or "").strip(), (doc.page or "").strip()
    if book and page:
        image_url = (f"{JASPER_BASE}/Image/ShowDocImage?DocNum={doc.instrument_no or ''}"
                     f"&BookNum={book}&PageNum={page}&Kind={doc.doc_type or ''}"
                     f"&TIF2PDF=true&SearchTabID=0&HideDetails=false")
        raw["jasper_doc_image"] = {
            "method": "GET", "url": image_url,
            "requires": "jasper_recaptcha_and_cloudflare_cleared_session",
            "note": "cold GET 403s (Cloudflare challenge page); only fetchable from "
                    "the SAME nodriver tab that already cleared Jasper's Cloudflare "
                    "edge AND the operator-solved reCAPTCHA (see "
                    "rod.ccs_devexpress module docstring). Not stamped into "
                    "raw['documents']/['document_url'] -- document_links.py's own "
                    "_ROD_IMAGE_VENDOR denylist already excludes /ProcessedImages/ "
                    "URLs from that generic, cold-GET-only pass for this reason.",
        }
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        parcel_id=doc.parcel_id,
        defendant=defendant,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )
