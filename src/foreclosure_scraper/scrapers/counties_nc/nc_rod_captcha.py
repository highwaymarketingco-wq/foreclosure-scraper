"""NC Register of Deeds sites with CAPTCHA/math gate — 9 counties.

ALL 9 URLS REWRITTEN 2026-10-12. Before this date only 2 of 9 (Brunswick,
Stokes) had ever been checked against a live site -- the other 7 had never
actually been verified, and every single one was dead: 5 hard DNS failures
(Iredell, Craven, Greene, Harnett, Randolph -- "Could not resolve host",
confirmed from two separate networks) plus Wake (404 -- the domain itself
was right, the code was just missing the real `/web` app path) and Durham
(the whole county domain family changed to dconc.gov). The old docstring's
gate-type claims below were therefore also unverified guesses in several
cases, not confirmed observations -- corrected where live evidence now
exists.

Sites and gate types (all confirmed live 2026-10-12 unless noted):
- rodrecords.wake.gov/web — real Google reCAPTCHA checkbox, confirmed by
  screenshot (Tyler Technologies "Self-Service" platform v2026.1.5). Old
  code hit the bare domain (404); the app lives under /web.
- rodweb.dconc.gov/web — Durham's new domain (county migrated away from
  durhamcountync.gov entirely). Same Tyler "Self-Service" platform as
  Wake -- gate very likely the same reCAPTCHA, not individually
  screenshotted.
- brunswick-live.inttek.net — math question, confirmed by screenshot
  ("Four Minus One Equals ___"), use math_captcha.py. Real post-gate
  search_path still unverified (gate itself not cleared).
- iredellnc.courthousecomputersystems.com — real Google reCAPTCHA,
  confirmed by screenshot ("Please Verify You are Not a Robot"). NOTE:
  this platform only covers records from 1964 forward; pre-1964 records
  need a second, separate system (cotthosting.com/NCIredellExternal) --
  out of scope for now, flagging it exists.
- greenenc.courthousecomputersystems.com — same Courthouse Computer
  Systems platform as Stokes/Iredell (both confirmed reCAPTCHA); this
  county's own site says the system went live Dec 2025. High-confidence
  reCAPTCHA by platform match, not individually screenshotted.
- us6.courthousecomputersystems.com/HarnettNC — SAME base domain as
  Stokes, just a different county path (shared multi-tenant platform).
  High-confidence reCAPTCHA by platform match.
- us5.courthousecomputersystems.com/RandolphNC2 — different server
  instance (us5, not us6) and an unexpected "2" suffix on the county
  code. Owner directly observed CAPTCHA + disclaimer live 2026-10-12 --
  this corrects the old docstring's "math question" guess, which was
  never actually verified against this (or any) live URL.
- us5.courthousecomputersystems.com/CravenNC2 — same us5 instance as
  Randolph. Same correction: owner-confirmed CAPTCHA + disclaimer live
  2026-10-12, not the old docstring's unverified "math question" guess.
- us6.courthousecomputersystems.com/StokesNC — real Google reCAPTCHA,
  confirmed by screenshot, behind a terms-of-use disclaimer.

LIVE RE-VERIFIED 2026-10-14 (source-completeness audit's "Needs YOU logged in"
list, final item -- see docs/source_completeness_audit_2026-10-13.md). Every
one of the above claims was re-checked against the live site, not trusted on
the 2-day-old docstring, per the sibling discovery earlier the same night that
5 other "needs login" files in that same list turned out to need no login at
all. Of these 9, 8 reconfirmed exactly as above -- Wake, Iredell, Craven,
Greene, Harnett, Randolph, Stokes all still show a real Google reCAPTCHA
widget live (confirmed via Playwright DOM query for an actual
`iframe[src*=recaptcha]`/`div.g-recaptcha`, not a string-grep on the page's
raw HTML -- see the Durham correction below for why the stronger check
matters), and Brunswick's math gate is still live. These 8 are left alone,
genuinely walled, same boundary this audit night already drew at Jasper
(`sc_rod_walled.py`, commit 7335c362): a real CAPTCHA this codebase cannot
automate.

- **Durham was WRONG and is now FIXED.** The 2026-10-12 entry's own words
  were "very likely the same reCAPTCHA [as Wake], not individually
  screenshotted" -- an inference by platform match, never actually checked.
  Worse: this was already WRONG the day it was written, and the correct
  answer was sitting in this same codebase. `rod/nc_tyler.py` (a
  name-search ROD enricher for existing leads, unrelated purpose, written
  2026-10-07) says in its own docstring: "Durham's disclaimer page loads
  Google's reCAPTCHA script but showed no challenge on 2026-10-07." Five
  days later this file's docstring guessed the opposite for the exact same
  site, without checking -- a real in-repo contradiction, the same class of
  bug this audit night already caught once in `sc_rod_cott.py` (Union
  "pay-per-view" vs. `rod/doc_images.py`'s own "free" registry). Live-
  verified 2026-10-14: a plain string search of Durham's raw HTML DOES
  contain "g-recaptcha" (it ships in this Tyler "Self-Service" tenant's
  shared JS bundle site-wide), which is exactly the false signal that made
  the 2026-10-12 guess plausible -- but a real DOM query
  (`page.query_selector("iframe[src*=recaptcha]")`) on both the disclaimer
  page AND the search page returns nothing. The actual gate is just the
  "I Accept" disclaimer button every Tyler Self-Service tenant has (id
  `submitDisclaimerAccept`) -- no CAPTCHA at all. Clicking it fires a
  client-side JS redirect, not a normal navigation, so a `networkidle` wait
  immediately after the click still sees the disclaimer page; it needs a
  real pause (confirmed live: <4s is enough) before the redirect lands on
  `/web/`. From there `/web/search/DOCSEARCH5S1` is directly reachable and
  returns real, live recording-date-filtered results with zero gate -- a
  14-day window live-pulled 1,243 real documents (5 tagged FORECLOSURE,
  264 DEED OF TRUST, etc.) on 2026-10-14. This tenant's result rows are
  **not** `<table>` markup at all -- a jQuery-Mobile `ui-listview` of
  `<li class="ss-search-row">` elements -- so the shared `_parse_html()`
  below (which only looks for `table tr`) would find zero rows even with
  the gate cleared. Durham gets its own flow (`_fetch_durham`), but NOT a
  second hand-rolled parser: `rod/nc_tyler.py` already has a tested one for
  this exact markup (`parse_selfservice`, built for its own name-search use
  case) -- reused here via `_durham_record_to_listing` rather than
  duplicated. Row capture itself is page-1-only (Tyler's ~100-row default
  page size) of the 90-day window,
  newest-first -- NOT full pagination (a 90-day window runs into the
  thousands of rows; out of scope for this pass, flagged here same as every
  other partial-coverage note in this codebase rather than silently claimed
  complete).

  Each row's primary document image IS viewable free, no login, no cart,
  INSIDE an authenticated browser session: the detail page
  (`/web/document/{documentid}`) embeds a PDF.js viewer whose iframe
  `data-href` is a `/web/document-image-pdf/...` route that returned a real
  `200 application/pdf` (live-verified on 2 real documents, 110KB/4-page and
  similar) when fetched through `page.request` -- i.e. still carrying the
  Playwright page's cookies. Deliberately **NOT** stamped via
  `document_links.stamp_documents`, after first implementing exactly that
  and then catching the mistake live: a bare `curl` (no cookies at all)
  against that same URL gets a `302` to `/web/user/disclaimer` with a fresh
  `Set-Cookie: JSESSIONID=...`, and adding a matching `Referer` header
  (the fix that worked for Union/Cott's image route earlier tonight) does
  NOT help -- this route checks a live server-side session, not the
  Referer. `enrichment_doc_ocr.py`'s `_fetch_doc` fetches every stamped
  `document_url` with a plain stateless `httpx.AsyncClient`, no cookie jar
  carried over from this scraper's Playwright run, so a stamped link here
  would silently 302 to the disclaimer HTML and fail OCR invisibly --
  exactly the "looks wired, produces nothing downstream" failure mode this
  codebase has hit before (e.g. the column-source silent-death pattern).
  Left as a flagged, documented gap rather than shipped as a working
  document link it isn't: the index-row data above (doc type, grantor,
  grantee, book/page, filing date) is the confirmed-working deliverable;
  the per-document image would need either a from-scratch rework of
  `enrichment_doc_ocr.py` to carry a session (out of scope here, cross-cuts
  every other scraper that module reads) or this scraper downloading the
  PDF bytes itself while the session is live and storing them some other
  way than a `raw` URL field (a bigger schema change, also out of scope).

- **Brunswick's math gate is confirmed live but NOT actually solvable by
  this codebase's `math_captcha.py` as written**, which matters because
  `solve_math_captcha()` returns `True` (claims success) while silently
  failing -- a real bug worth flagging even though it doesn't change
  Brunswick's walled status. Live-tested 2026-10-14: the specific arithmetic
  question ("Four Minus One Equals ___" per the 2026-10-12 screenshot) is
  rendered as a CAPTCHA **image** (`getpng.php?a=N&b=M`), not as visible
  text anywhere on the page -- `math_captcha.solve_math_question()` only
  ever reads `page.inner_text("body")`, so it has nothing to OCR and no
  real question to parse. Instead it spuriously pattern-matches the
  Register of Deeds office's own phone number in the page footer
  ("(910) 253-2690") as if it were the arithmetic expression "253-2690",
  "solves" it to -2437, fills the answer field, submits, and reports
  `solved=True` -- but the resulting page is byte-for-byte the same
  disclaimer/login page as before the submit (confirmed by diffing
  `inner_text()` before/after), i.e. the gate was never actually cleared.
  Left alone: genuinely walled (an image-rendered math CAPTCHA, which is a
  materially different and harder problem than the text-based one this
  module was built for), not patched as part of this pass since fixing
  `math_captcha.py` itself is a separate, broader change outside this file
  and outside this audit's current scope -- flagged for whoever picks it up
  next instead of silently papering over the false-positive return value.

**CORRECTION 2026-10-14 (cont.) -- `math_captcha.py`'s false positive is now
FIXED, and Brunswick turned out to be genuinely solvable, not just
correctly-reported-failed.** `solve_math_captcha()` no longer regexes
`page.inner_text("body")` at all -- it scopes question-text extraction to
the `<fieldset>`/`<form>` immediately around the answer input (Brunswick's
real markup is `<fieldset class="captcha">`, several DOM levels away from
the footer's phone number, which sits in a sibling section of the same
page-spanning outer `<form>`), strips any phone-number-shaped substring as a
second independent guard, and -- the part that actually unlocks Brunswick --
detects an image-only question and OCRs it via this codebase's existing
free-tier-first Gemini vision plumbing
(`enrichment_vision._parse_gemini_keys`/`_parse_json_response`, the same
key-rotation `enrichment_doc_ocr.py` uses) instead of either guessing or
giving up. Brunswick's question turned out to be FOUR separate word-images
(`getpng.php?a=N&b=M` -- confirmed live by fetching and visually reading the
actual PNGs: one page read "Five"/"Plus"/"Nine"/"Equals" = 14, another
"Seven"/"Minus"/"Zero"/"Equals" = 7; the `a`/`b` query params are NOT the
literal operands, just opaque render params), which `_solve_image_question`
sends to Gemini together as one multi-image call so the words are read in
the right order. Live-verified end-to-end against the real site 2026-10-14,
twice, with NO browser in the loop for this specific check (httpx replaying
the real session/cookies and the real form POST, to avoid running Chromium
locally during an active Mac memory/swap crisis -- the Playwright code path
itself is covered by `tests/test_math_captcha.py`'s `_FakePage`, which
mirrors the exact Page API `solve_math_captcha()` calls): fetched the live
page, OCR'd the real question image(s), POSTed the computed answer with the
session it was issued under, and got back a genuinely different page (no
more captcha field) both times -- the real gate cleared for real, not just a
plausible-looking return value. OCR reliability is tied to whatever Gemini
model/quota this codebase is configured with at the time (same dependency
every other OCR-driven enricher already has) -- one live attempt hit a
transient "503 model overloaded" across all 9 rotated keys on the default
model, and a deliberately-weaker model substituted for comparison
(`gemini-2.5-flash-lite`) misread one of the four images on 1 of 3 repeated
trials against the SAME saved image set. Neither failure mode becomes a new
false positive: when OCR can't read the image, `_solve_image_question`
returns `None` and `solve_math_captcha` reports `False`; when OCR confidently
misreads it, the new post-submit `_gate_still_present` check (comparing the
page before/after submit, the exact comparison the old code skipped) catches
the wrong answer and still reports `False` -- confirmed live in the misread
case above (gate stayed present after the bad answer was submitted). Net:
Brunswick now succeeds when Gemini OCR is available and correct, and fails
CLOSED (reports unsolved, same as before) when it isn't -- never a silent
wrong "success" either way. 4 of 4 live attempts in this session solved the
CAPTCHA correctly (one earlier side-by-side comparison against a weaker
model, not the one this codebase actually ships, did misread one image --
see `math_captcha.py`'s own module docstring). See `tests/test_math_captcha.py`
for the full test coverage (the phone-number false-positive case, legitimate
text-based questions, and this OCR path with a mocked Gemini call using the
real live word-image evidence above).

Clearing the CAPTCHA is NOT the whole gate, though -- live-followed one
layer further 2026-10-14: the page right after a correct CAPTCHA submit is
a SECOND gate, a disclaimer accept/decline page (structurally the same
pattern as Durham's `#submitDisclaimerAccept`, just an anchor link here
instead of a button: `<a href=".../index.ntk?s=...">I have read, and agree
with the License above</a>`). Following that link lands on the real site
menu ("Please select the type of search you want to perform" -- Combined
Real Property/MAPS, Births, Deaths, Marriages, Notary, Book/Page Direct),
confirming the full CAPTCHA+disclaimer chain genuinely reaches Brunswick's
real UI, not just a second dead end. This was reconnaissance only (plain
`httpx` replaying the session, same reasoning as the CAPTCHA verification
above) -- NOT wired into `fetch()`/`_COUNTY_SITES` here. Brunswick still
needs: (1) the disclaimer-accept step added to this file's `gate == "math"`
branch (the same shape as `_fetch_durham`'s accept click, just needs its
own helper since the control here is a link, not a button), (2) the
"Combined Real Property/MAPS" search clicked into and its date-range/
result markup captured (unknown shape -- not yet observed), and (3)
whatever parser that markup turns out to need, the same way Durham got
`_durham_record_to_listing`/`parse_selfservice` instead of the generic
`_parse_html`. None of that is done here -- this pass only fixes
`math_captcha.py`'s false positive and confirms the CAPTCHA layer itself is
now genuinely solvable; wiring Brunswick's actual lead capture through the
two gates above is a follow-up, flagged here rather than silently implied
by "Brunswick is now solvable."

Strategy:
1. Launch Playwright browser (headful -- required; see the `headless=False`
   note on the browser launch call below).
2. Navigate to the entry/disclaimer page.
3. Durham (`gate == "none"`): click the disclaimer Accept button, no CAPTCHA
   -- see `_fetch_durham`.
4. Otherwise: if math captcha, try math_captcha.solve_math_captcha(page); if
   reCAPTCHA V2, try enrichment_recaptcha_audio.solve_recaptcha_v2(page).
   reCAPTCHA V2 is live-reverified 2026-10-14 to never actually get past
   Wake/Iredell/Craven/Greene/Harnett/Randolph/Stokes's real gates (see
   above) -- these 7 are expected to always fall through to the WAF-bypass
   attempt and then `continue` past, genuinely blocked, by design. Brunswick
   (`gate == "math"`) is DIFFERENT as of the 2026-10-14 (cont.) correction
   above: `solve_math_captcha` now actually solves it (OCRs the image
   question via Gemini) when quota/the model is available, and correctly
   returns `False` -- same as the other 7 -- when it isn't, rather than the
   old silent wrong "success".
5. Once through, search for deeds by date range.
6. Parse results (Durham via its own row parser; the rest via `_parse_html`,
   which only matches `<table>` markup and would need rework if any of the
   remaining 7-always-walled counties (or Brunswick, on a run where OCR
   doesn't clear it) ever actually clears its gate -- none of them use a
   `<table>` either, per the live HTML pulled 2026-10-14; Brunswick's own
   post-gate markup has not been captured/parsed here yet, a follow-up item
   now that the gate itself can clear).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_COUNTY_SITES = {
    "wake": {"url": "https://rodrecords.wake.gov/web", "gate": "recaptcha", "search_path": "/user/disclaimer"},
    # gate "none": live-reverified 2026-10-14 -- no CAPTCHA at all, just a
    # disclaimer click-through. See module docstring's Durham correction.
    "durham": {"url": "https://rodweb.dconc.gov/web", "gate": "none", "search_path": "/search/DOCSEARCH5S1"},
    "brunswick": {"url": "https://brunswick-live.inttek.net", "gate": "math", "search_path": "/search"},
    "iredell": {"url": "https://iredellnc.courthousecomputersystems.com", "gate": "recaptcha", "search_path": "/search"},
    "craven": {"url": "https://us5.courthousecomputersystems.com/CravenNC2", "gate": "recaptcha", "search_path": "/search"},
    "greene": {"url": "https://greenenc.courthousecomputersystems.com", "gate": "recaptcha", "search_path": "/search"},
    "harnett": {"url": "https://us6.courthousecomputersystems.com/HarnettNC", "gate": "recaptcha", "search_path": "/search"},
    "randolph": {"url": "https://us5.courthousecomputersystems.com/RandolphNC2", "gate": "recaptcha", "search_path": "/search"},
    "stokes": {"url": "https://us6.courthousecomputersystems.com/StokesNC", "gate": "recaptcha", "search_path": "/search"},
}


class NcRodCaptchaScraper(BaseScraper):
    """NC ROD sites with CAPTCHA/math gate — Playwright + auto-solver."""

    slug = "counties_nc.nc_rod_captcha"
    name = "NC ROD CAPTCHA Sites"
    category = "rod"
    timeout_s = 900.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_rod_captcha.no_playwright")
            return results

        async with async_playwright() as p:
            # headless=False: confirmed live 2026-10-12 -- the Courthouse
            # Computer Systems platform (Stokes/Iredell/Greene/Harnett/
            # Randolph/Craven, 6 of these 9 counties) 403s headless
            # Chromium even on a correct, live URL and 200s the identical
            # request headful. Same bot-detection pattern already proven
            # and fixed for polk_tax.py -- requires a real display
            # (DISPLAY=:99 / Xvfb on the VM, same as Polk/Avalon/Morganton).
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for county, cfg in _COUNTY_SITES.items():
                page = None
                try:
                    page = await browser.new_page()
                    entry_url = cfg["url"]
                    log.info("nc_rod_captcha.fetching", county=county)

                    await page.goto(entry_url, timeout=30000)
                    await page.wait_for_load_state("networkidle", timeout=10000)

                    gate = cfg["gate"]

                    if gate == "none":
                        # Durham: no CAPTCHA, just the disclaimer Accept button --
                        # see module docstring's 2026-10-14 correction. Completely
                        # different DOM (no <table>), so it gets its own parser
                        # instead of the generic search-fill + _parse_html below.
                        county_results = await self._fetch_durham(page, entry_url, cfg["search_path"])
                        results.extend(county_results)
                        await page.close()
                        log.info("nc_rod_captcha.county_done", county=county, found=len(county_results))
                        continue

                    gate_cleared = False

                    if gate == "math":
                        try:
                            from ...math_captcha import solve_math_captcha
                            gate_cleared = await solve_math_captcha(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.math_failed", county=county, error=str(exc)[:160])

                    elif gate == "recaptcha":
                        try:
                            from ...enrichment_recaptcha_audio import solve_recaptcha_v2
                            gate_cleared = await solve_recaptcha_v2(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.recaptcha_failed", county=county, error=str(exc)[:160])

                    if not gate_cleared:
                        log.info("nc_rod_captcha.gate_failed_try_waf", county=county)
                        try:
                            from ...enrichment_waf_oss import solve_waf_via_browser
                            gate_cleared = await solve_waf_via_browser(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.waf_failed", county=county, error=str(exc)[:160])
                        if gate_cleared:
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                        else:
                            log.warning("nc_rod_captcha.gate_blocked", county=county)
                            await page.close()
                            continue

                    search_url = f"{entry_url}{cfg['search_path']}"
                    await page.goto(search_url, timeout=30000)

                    cutoff = (datetime.now() - timedelta(days=90))
                    cutoff_str = cutoff.strftime("%m/%d/%Y")
                    end_str = datetime.now().strftime("%m/%d/%Y")

                    for selector in [
                        "input[name*='from'], input[name*='start'], input[name*='begdate']",
                        "input[name*='to'], input[name*='end'], input[name*='enddate']",
                    ]:
                        try:
                            inputs = await page.query_selector_all(selector)
                            if len(inputs) >= 2:
                                await inputs[0].fill(cutoff_str)
                                await inputs[1].fill(end_str)
                                break
                        except Exception:
                            pass

                    for btn_sel in [
                        "button[type='submit']",
                        "input[type='submit']",
                        "a:has-text('Search')",
                        "#btnSearch",
                    ]:
                        try:
                            btn = await page.query_selector(btn_sel)
                            if btn:
                                await btn.click()
                                break
                        except Exception:
                            pass

                    await page.wait_for_load_state("networkidle", timeout=15000)

                    html = await page.content()
                    results.extend(self._parse_html(html, county, entry_url))

                    await page.close()
                    log.info("nc_rod_captcha.county_done", county=county, found=len(results))

                except Exception as exc:
                    log.warning("nc_rod_captcha.county_error", county=county, error=str(exc)[:200])
                    if page:
                        try:
                            await page.close()
                        except BaseException:
                            pass

            await browser.close()

        return results

    async def _fetch_durham(self, page: Any, entry_url: str, search_path: str) -> list[Listing]:
        """Durham ROD: disclaimer click-through only, no CAPTCHA (confirmed live
        2026-10-14 -- see module docstring's Durham correction for the full
        evidence, including why the 2026-10-12 "very likely the same reCAPTCHA"
        guess was wrong). Tyler "Self-Service" platform, same as Wake, but this
        tenant never actually renders a recaptcha widget.
        """
        results: list[Listing] = []

        try:
            accept_btn = await page.wait_for_selector("#submitDisclaimerAccept", timeout=10000)
            await accept_btn.click(force=True)
            # The Accept click fires a client-side JS redirect, not a normal
            # navigation -- a `networkidle` wait immediately after the click
            # still sees the disclaimer page (confirmed live). Give the
            # redirect time to land on /web/ before moving on.
            await page.wait_for_timeout(4000)
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_disclaimer_failed", error=str(exc)[:160])
            return results

        search_url = f"{entry_url}{search_path}"
        try:
            await page.goto(search_url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)

            cutoff = datetime.now() - timedelta(days=90)
            start_str = cutoff.strftime("%m/%d/%Y")
            end_str = datetime.now().strftime("%m/%d/%Y")

            start_input = await page.wait_for_selector(
                "#field_RecordingDateID_DOT_StartDate", timeout=10000)
            end_input = await page.query_selector("#field_RecordingDateID_DOT_EndDate")
            await start_input.fill(start_str)
            await end_input.fill(end_str)

            search_btn = await page.query_selector("#searchButton")
            if not search_btn:
                log.warning("nc_rod_captcha.durham_no_search_button")
                return results
            await search_btn.click()
            await page.wait_for_timeout(5000)
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_search_failed", error=str(exc)[:160])
            return results

        # NOTE: page 1 only (Tyler's ~100-row default page size), newest-first,
        # of a 90-day window -- not full pagination. A 90-day window runs into
        # the thousands of rows on this platform; see module docstring.
        html = await page.content()
        from ...rod.nc_tyler import parse_selfservice
        try:
            records = parse_selfservice(html)
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_parse_failed", error=str(exc)[:160])
            return results
        log.info("nc_rod_captcha.durham_rows", count=len(records))

        for record in records:
            li = self._durham_record_to_listing(record, search_url)
            if li is not None:
                results.append(li)

        return results

    def _durham_record_to_listing(self, record: Any, source_url: str) -> Listing | None:
        """Build a Listing from one `rod.nc_tyler.parse_selfservice` IndexRecord.
        Reuses that already-tested parser (same `rod/nc_tyler.py` module that
        already correctly found, on 2026-10-07, that Durham's disclaimer page
        "loads Google's reCAPTCHA script but showed no challenge" -- a finding
        this file's own 2026-10-12 entry contradicted and got wrong, see the
        module docstring's Durham correction) instead of hand-rolling a second
        parser for the exact same HTML shape. Mirrors the shared `_parse_html`'s
        raw-key shape (county/doc_type/filing_date/grantor/grantee/book_page)
        so no new raw keys need registering in web_artifact.py."""
        doc_number = (record.instrument_no or "").strip()
        if not doc_number:
            return None

        book_page = " ".join(
            p for p in (
                f"BT: {record.index_code}" if record.index_code else "",
                f"B: {record.book}" if record.book else "",
                f"P: {record.page}" if record.page else "",
            ) if p
        )

        return Listing(
            source=self.slug,
            source_url=source_url,
            listing_type=ListingType.UNKNOWN,
            property_kind=PropertyKind.UNKNOWN,
            county="Durham",
            state="NC",
            case_number=doc_number,
            owner_name=", ".join(record.grantees) or None,
            plaintiff=", ".join(record.grantors) or None,
            legal_description=record.description or None,
            raw={
                "county": "durham",
                "doc_type": record.doc_type or "",
                "filing_date": record.recorded or "",
                "grantor": ", ".join(record.grantors),
                "grantee": ", ".join(record.grantees),
                "book_page": book_page,
            },
        )

    def _parse_html(self, html: str, county: str, base_url: str) -> list[Listing]:
        """Parse deed search results from HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table.results tr, table.grid tr, .search-result, table tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            book_page = cells[0].get_text(strip=True)
            filing_date = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            doc_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            grantor = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            grantee = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            if not book_page or book_page == "\xa0":
                continue

            results.append(Listing(
                source=self.slug,
                source_url=base_url,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                county=county.title(),
                state="NC",
                case_number=book_page,
                owner_name=grantee,
                plaintiff=grantor,
                raw={
                    "county": county,
                    "doc_type": doc_type,
                    "filing_date": filing_date,
                    "grantor": grantor,
                    "grantee": grantee,
                    "book_page": book_page,
                },
            ))

        return results
