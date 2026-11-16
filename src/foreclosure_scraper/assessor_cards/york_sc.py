"""York County SC property-card fetch -- the Cloudflare/WAF wall, actually closed.

THE WALL gap_matrix flags (hermes_handoff.md section 2, "Bot-wall, build in-house"):
www.yorkcountysc.gov returns a static Cloudflare WAF block page to a plain client --
LIVE-CONFIRMED 2026-11-16: curl/httpx get HTTP 403, `server: cloudflare`, a
"Sorry, you have been blocked" / "Attention Required!" page ("This website is using
a security service... The action you just performed triggered the security
solution"), CF-RAY e.g. a5b76f87bb3733ef-ATL. This is a static WAF-rule block, NOT an
interactive Turnstile/"Just a moment..." JS challenge -- no widget to solve, just a
request the edge decided to refuse.

THE FIX, same convention as chester_delinquent_tax.py's fallback and this package's
own qpublic_render.py (Scrapling StealthyFetcher, camoufox real-browser render,
`solve_cloudflare=True`): LIVE-CONFIRMED 2026-11-16, a plain `StealthyFetcher.
async_fetch(".../216/Tax-Collection", solve_cloudflare=True)` returns HTTP 200 with
the real page (Scrapling logs "No Cloudflare challenge found" -- there was no
interactive challenge to solve; the real browser's TLS/HTTP fingerprint alone clears
the WAF rule that blocks curl/httpx). So the wall itself is NOT genuinely unbeatable
with this project's existing stealth approach; it folds to the same technique already
used elsewhere in this codebase, no new bypass invented.

THE REAL SOURCE, once past the wall: that Tax-Collection page links to York's actual
per-parcel lookup tool -- NOT the `counties_sc.york_delinquent_tax` ArcGIS
FeatureServer (a different, already-open source: the county's current tax-SALE list,
~853 rows, no login/CAPTCHA/Cloudflare at all, see that module) -- but a "Property
Card Search" at evolvepublic.yorkcountygov.com, an "Evolve Public" / Infovision
Software app. LIVE-CONFIRMED 2026-11-16: that host has NO Cloudflare/WAF of its own
(plain HTTPS GET: 200 in <1s); it is reachable over plain HTTP too via a real browser,
though plain curl on port 80 alone times out at the TCP level (an ordinary port/
firewall quirk, unrelated to bot detection -- irrelevant once you go through
www.yorkcountysc.gov's own links, which resolve straight to the https host).

THE SEARCH IS A STATEFUL ASP.NET UpdatePanel APP (ScriptManager partial-postback,
panel ids `UP_MenuLeft`/`UP_Results`/`UP_MyAccount`), not a plain GET-queryable page.
LIVE-DIAGNOSED 2026-11-16: driving it with plain httpx (hand-rolled __VIEWSTATE/
__EVENTVALIDATION POSTs, no real browser) reliably returns the blank search form
(zero results) for every search type tried (Owner Name "BECKFORD", Address "3205
BENTWOOD LN", TaxMapID in 4 formats) -- NOT a data problem, a protocol one: the
server's own async-postback lifecycle needs the real browser's MicrosoftAjax.js
driving it, exactly as qpublic_render.py's docstring already found for a different
Schneider WebForms app ("NOT submittable via this project's get_text(wall_bypass=True)
GET-only convention"). Confirmed by then doing it with a REAL StealthyFetcher browser
session (click the "Property Card" nav item, `select_option` the `DL_SearchType`
dropdown to "TaxMapID" or "Owner Name", type into `#TB_SearchText1`, click
`#BT_Search`) -- LIVE: Owner Name "BECKFORD" returned 2 real rows (TMS 5550000151
"BECKFORD ELSETA R" and 6030000050 "BECKFORD DANIELLE"); TaxMapID "5550000151" (the
FLAT, undashed form straight off the ArcGIS feed -- no reformatting needed) returned
the same single real row. So the flat TMS format works fine; the httpx failures above
were protocol-only, not a format guess.

Each result row's "P" indicator link (`GV_SearchResults_LBT_ResultsIndicator_0`, an
ASP.NET LinkButton, `__doPostBack` -- NOT a window.open/popup, despite the search
landing page's "ensure popups are enabled" notice, which turned out to describe a
same-tab navigation) is the card itself: clicking it navigates the browser straight to
a generated PDF at `https://evolvepublic.yorkcountygov.com/tempview/<token>.pdf` --
LIVE-CONFIRMED 2026-11-16 for TMS 5550000151, and that URL fetched clean via a BARE
httpx GET, no cookies/session needed (200, 4-page real PDF).

THE CEILING, found by actually reading that PDF (not assumed): it is a SCAN of a
legacy paper "SOUTH CAROLINA - COUNTY" assessor record card -- hand-filled, not
machine text. It carries ownership/transfer history (grantee, date, liber/folio,
sale $), assessed land+improvement value by year, and a CONSTRUCTION/INTERIOR table
that sometimes has a handwritten "Baths" count (2026-11-16's test parcel: "2") but no
reliable "Rooms"/bedroom count (blank on that same card) -- i.e. a PARTIAL, OCR-gated
`beds_baths` source at best, nothing like qPublic's clean HTML two-column fact table.
It has NO delinquent-tax field anywhere on any of its 4 pages: no years-delinquent, no
balance, no rollback, no aging bucket. So this source, even fully wired, cannot close
`multi_year_delinquent_tax` / `rollback_exposure` / `tax_aging_surfaced` /
`two_year_delinquent` -- it is the wrong document type for those 4 columns, not a wall
problem.

THE TREASURER SIDE (where a years-delinquent breakdown would actually live) was
chased to its real end, not abandoned early: www.yorkcountysc.gov's own "Tax
Collection" -> "Online Payments" (/693/Online-Payments) -> "Taxes" link
(yorkcountygov.com/taxes, 302 to secured-server.biz/YorkCounty/HP/, itself NOT
Cloudflare-walled, plain curl 200) lands on a generic CivicPlus sitewide-search widget
(id="searchQuery", a "what are you searching for" box with year/type/status FILTER
dropdowns -- not a parcel lookup), and the page's only other tax-relevant link
(yorkcountygov.com/EPayment) redirects right back to the SAME Online-Payments page.
No parcel-keyed, years-delinquent treasurer tool was found behind any link the
county's own site actually offers, despite following every one. This may mean the
real tool sits somewhere this pass didn't reach (not exhaustively ruled out -- the
site's internal search box itself was not queried), or that York, unlike Florence
(`enrichment_florence_tax_inquiry.py`'s web.florenceco.org CGI), simply does not
publish a per-parcel multi-year delinquency lookup online at all. Left OPEN rather
than guessed; see the memory file this session wrote
(project_york_tax_portal_waf_2026-11-16.md) for the exact link chain to resume from.

WHAT THIS MODULE ACTUALLY DOES: resolves a York TMS to the real property-card PDF URL
(or its bytes), end to end, through the confirmed working path above. It does NOT
parse the card (no OCR/vision wired in this pass -- `enrichment_doc_ocr.py`'s
Gemini-first OCR path is the natural next step for the handwritten baths count, not
rebuilt here) and is NOT registered as a board scraper or wired into any backfill:
there is nothing verified to write onto the board yet (no tax-delinquency fields
exist to write, and beds_baths would need the OCR step first) -- landing it unwired is
the same honest-partial convention qpublic_render.py already uses for Edgefield.

Slug: none (not a BaseScraper). Called directly, like `qpublic_render.fetch(li)`.
"""
from __future__ import annotations

import re

import httpx
import structlog

from .base import cf_solving_disabled

log = structlog.get_logger()

SEARCH_URL = "http://evolvepublic.yorkcountygov.com/?Search=assessor"
_TIMEOUT_MS = 150000


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _visible_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


async def _resolve_pdf_url(tms: str, *, owner: str | None = None) -> str | None:
    """Drive the Evolve/Infovision search with a real browser session and return
    the generated property-card PDF URL for the FIRST matching row, or None.

    search_type is TaxMapID when `tms` is given (the flat digit string straight
    off the ArcGIS feed / board parcel_id -- confirmed live, no reformatting);
    Owner Name is only used by the caller as a fallback when a TMS search comes
    back empty (some parcels index differently; see qpublic_render.py's own
    "normal address-matching miss rate, not a defect" precedent).

    RETRIES the whole search+click round up to 3 times: LIVE-DIAGNOSED 2026-11-16,
    the indicator click sometimes lands a real postback (no error, `ind` present
    both before and after) that just never navigates `page.url` to the tempview
    PDF -- 1/1 and 1/3 cold-run misses seen back to back, immediately followed by
    a clean success on a fresh attempt in the same process. Same "cold-start
    flakiness in the existing bypass, not a wall/config problem" shape
    qpublic_render.py's own `_render()` already documents and retries for a
    different Schneider app; mirrored here rather than re-litigated."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("york_sc.scrapling_missing")
        return None

    holder: dict = {}

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        async def do_search(search_type: str, query: str) -> bool:
            link = await page.query_selector("a:has-text('Property Card')")
            if link:
                await link.click()
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(1200)
            sel = await page.query_selector("select#DL_SearchType")
            if sel:
                try:
                    await sel.select_option(label=search_type)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(1200)
            box = await page.query_selector("input#TB_SearchText1")
            if not box:
                return False
            await box.click()
            await box.fill("")
            await box.type(query, delay=25)
            btn = await page.query_selector("input#BT_Search")
            if not btn:
                return False
            await btn.click()
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            ind = await page.query_selector(
                "#GV_SearchResults_LBT_ResultsIndicator_0"
            )
            return ind is not None

        def _is_pdf_url(u: str | None) -> bool:
            return bool(u) and u.lower().endswith(".pdf") and "/tempview/" in u.lower()

        for round_num in range(3):
            found = False
            if tms:
                found = await do_search("TaxMapID", tms)
            if not found and owner:
                found = await do_search("Owner Name", owner)
            if not found:
                if round_num < 2:
                    await page.wait_for_timeout(1500)
                    continue
                return

            ind = await page.query_selector(
                "#GV_SearchResults_LBT_ResultsIndicator_0"
            )
            if not ind:
                if round_num < 2:
                    continue
                return
            try:
                await ind.click()
            except Exception:
                if round_num < 2:
                    continue
                return
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            # Poll page.url rather than trust networkidle alone: LIVE-DIAGNOSED,
            # the postback's navigation to the tempview PDF can start a beat
            # after networkidle already resolved on the pre-click page.
            for _ in range(10):
                try:
                    if _is_pdf_url(page.url):
                        break
                except Exception:
                    break
                await page.wait_for_timeout(1000)
            try:
                if _is_pdf_url(page.url):
                    holder["url"] = page.url
                    return
            except Exception:
                pass
            if round_num < 2:
                # Didn't navigate -- go back to the search URL for a clean retry.
                try:
                    await page.goto(SEARCH_URL, timeout=20000)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)

    try:
        await StealthyFetcher.async_fetch(
            SEARCH_URL, headless=True, timeout=_TIMEOUT_MS,
            solve_cloudflare=not cf_solving_disabled(), network_idle=True,
            page_action=page_action,
        )
    except Exception as exc:
        log.debug("york_sc.render_error", error=str(exc)[:150])

    url = holder.get("url")
    if url and url.lower().endswith(".pdf") and "/tempview/" in url.lower():
        return url
    return None


async def fetch_card_pdf_url(parcel_id: str | None, *, owner_name: str | None = None) -> str | None:
    """Resolve a York County TMS (flat digits, e.g. "5550000151") to its real
    property-card PDF url, or None on no-match / render failure. Defensive:
    never raises."""
    tms = _digits(parcel_id)
    if not tms and not owner_name:
        return None
    try:
        return await _resolve_pdf_url(tms, owner=owner_name)
    except Exception:
        log.debug("york_sc.fetch_failed", parcel_id=parcel_id)
        return None


async def fetch_card_pdf_bytes(parcel_id: str | None, *, owner_name: str | None = None) -> bytes | None:
    """Same as fetch_card_pdf_url, but also downloads the PDF bytes (plain
    httpx GET -- LIVE-CONFIRMED the tempview host needs no cookies/session).
    Returns None on any failure; never raises."""
    url = await fetch_card_pdf_url(parcel_id, owner_name=owner_name)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return r.content
    except Exception:
        log.debug("york_sc.pdf_download_failed", url=url[:140])
    return None
