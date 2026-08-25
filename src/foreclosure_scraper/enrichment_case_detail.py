"""SC Public Index + NC eCourts case-detail scraper for property addresses.

For lis pendens listings whose address is currently a synthesized placeholder
("Lis Pendens 2026-CP-04-00921 — Marcus Brown"), render the actual case detail
page on the public court portal and parse the property address from the
docket entries / lis pendens filing text.

SC Public Index (publicindex.sccourts.org) and NC eCourts (Tyler Odyssey) both
require Scrapling's StealthyFetcher because they sit behind F5/anti-bot
challenges. Each render takes ~20-40s; capped concurrency to be polite.

Free, Scrapling stealth, no auth.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


# SC county code mapping for case# → county translation.
SC_COUNTY_BY_CODE = {
    "04": "Anderson",
    "07": "Bamberg",  # not in our footprint, but valid
    "11": "Cherokee",
    "23": "Greenville",  # adjacent
    "30": "Laurens",
    "37": "Oconee",
    "39": "Pickens",
    "42": "Spartanburg",
    "44": "Union",
}


# Property-address patterns we look for in case detail text.
ADDR_RE = re.compile(
    r"(\d{1,5}\s+[A-Z][A-Za-z .'\-]{3,40}?\s+"
    r"(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|"
    r"Parkway|Pkwy|Terrace|Terr)\.?(?:\s*,\s*[A-Z][a-zA-Z .'\-]+)?"
    # \d{0,5} — zip is optional. Was \d{5}? which is exactly 5 digits
    # (the ? is a lazy quantifier on the {5} count, NOT a make-optional
    # marker), causing the regex to fail on any address without a zip.
    r"(?:\s*,?\s*(?:NC|SC))?\s*\d{0,5})",
    re.I,
)


def _sc_case_urls(case_number: str) -> list[str]:
    """Build candidate SC Public Index case-detail URLs. Try multiple URL
    patterns since the portal accepts at least two."""
    m = re.match(r"(\d{4})-CP-(\d{2})-(\d{4,6})", case_number.strip())
    if not m:
        return []
    year, county_code, num = m.groups()
    county = SC_COUNTY_BY_CODE.get(county_code)
    if not county:
        return []
    case_clean = f"{year}CP{county_code}{num}"
    base = f"https://publicindex.sccourts.org/{county}/PublicIndex/"
    return [
        # Simple form (existing scraper uses this)
        f"{base}CaseDetails.aspx?CaseNum={case_clean}",
        # Full form
        f"{base}CaseDetails.aspx?County={county_code}&CourtAgency={county_code}001&Casenum={case_clean}",
        # Dashed form
        f"{base}CaseDetails.aspx?CaseNum={case_number.strip()}",
    ]


async def _fetch_case_detail_html(url: str, case_number: str = "", county: str = "") -> Optional[str]:
    """Render the SC case detail page.

    Strategy (in priority order):
    1. nodriver (headless=False) — the ONLY method that works for SC Public Index.
       Requires the full user flow: disclaimer → search form → case detail.
    2. StealthyFetcher (headless=True) — works for some Tyler/NC pages but
       gets HTTP 406 on SC Public Index CaseDetails.aspx.
    """
    # --- Method 1: nodriver full-flow for SC Public Index ---
    if county and case_number:
        html = await _fetch_sc_case_nodriver(case_number, county)
        if html and len(html) > 2000:
            return html

    # --- Method 2: StealthyFetcher fallback (works for Tyler/NC, NOT SC) ---
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    async def page_action(page):
        try:
            await page.wait_for_selector("table, body, .DataGrid, #ContentPlaceHolder1",
                                         timeout=15000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        result = await asyncio.wait_for(
            StealthyFetcher.async_fetch(
                url, headless=True, network_idle=True, timeout=45000,
                page_action=page_action,
            ),
            timeout=60.0,
        )
    except (asyncio.TimeoutError, Exception):
        return None

    body = getattr(result, "body", b"")
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")


# ── Single reusable browser (8GB-safe) ─────────────────────────────────────
# Old code started a NEW Chrome per case lookup → 2,205 browser start/stop
# cycles on 8GB = OOM. Now we keep ONE browser alive for the entire batch,
# navigate sequentially, and close only when done.
_browser_ctx: dict = {"browser": None, "headless": None}


async def _get_browser():
    """Get or create a single reusable nodriver browser instance.

    Tries headless=True first (new nodriver may pass F5). Falls back to
    headless=False if headless fails. Only ONE instance at a time.
    """
    if _browser_ctx["browser"] is not None:
        try:
            # Verify the browser is still alive
            _ = await _browser_ctx["browser"].tabs
            return _browser_ctx["browser"]
        except Exception:
            _browser_ctx["browser"] = None

    try:
        import nodriver as uc
    except ImportError:
        return None

    # Try headless first — if F5 blocks it, fall back to headless=False
    for headless in (True, False):
        try:
            _browser_ctx["browser"] = await uc.start(headless=headless)
            _browser_ctx["headless"] = headless
            log.info("nodriver.browser_started", headless=headless)
            return _browser_ctx["browser"]
        except Exception as e:
            log.warning("nodriver.start_failed", headless=headless, error=str(e))
            continue
    return None


async def _close_browser():
    """Close the reusable browser if open."""
    if _browser_ctx["browser"] is not None:
        try:
            await _browser_ctx["browser"].close()
        except Exception:
            pass
        _browser_ctx["browser"] = None


async def _fetch_sc_case_nodriver(case_number: str, county: str) -> Optional[str]:
    """Navigate SC Public Index via nodriver to reach a case detail page and
    return its HTML.

    Uses the shared reusable browser (single instance, no per-query launch).
    Tries headless=True first; falls back to headless=False if F5 requires it.

    Flow: landing page → accept disclaimer → search by case number → click
    case link → get case detail HTML.
    """
    browser = await _get_browser()
    if browser is None:
        return None

    base = f"https://publicindex.sccourts.org/{county}/PublicIndex/"
    search_url = f"{base}PISearch.aspx"

    try:
        page = await browser.get(search_url)

        # Step 1: Accept disclaimer if present
        try:
            accept_btn = await page.find("ButtonAccept", best_match=True)
            if accept_btn:
                await accept_btn.click()
                await asyncio.sleep(1.5)
        except Exception:
            pass  # may not have disclaimer on all counties

        # Step 2: Select court type and enter case number
        try:
            court_select = await page.find("DropDownListCourtType", best_match=True)
            if court_select:
                await court_select.click()
                await asyncio.sleep(0.3)
                await page.evaluate(
                    "document.getElementById('ContentPlaceHolder1_DropDownListCourtType')"
                    ".selectedIndex = 1;"  # Common Pleas
                )
                await asyncio.sleep(0.3)
        except Exception:
            pass

        case_input = await page.find("TextBoxCaseNumber", best_match=True)
        if case_input:
            await case_input.clear()
            await case_input.send_keys(case_number)
            await asyncio.sleep(0.3)

        # Click search button
        search_btn = await page.find("ButtonSearch", best_match=True)
        if search_btn:
            await search_btn.click()
            await asyncio.sleep(2.5)
        else:
            await case_input.send_keys("\n")
            await asyncio.sleep(2.5)

        # Step 3: Click on the case link in the results
        try:
            case_link = await page.find("openDetails", best_match=True)
            if case_link:
                await case_link.click()
                await asyncio.sleep(3.0)
        except Exception:
            pass

        # Step 4: Get the case detail HTML
        html = await page.get_content()
        return html

    except Exception as e:
        log.debug("nodriver_sc_case_error", error=str(e))
        # If browser died, clear it so next call creates a fresh one
        _browser_ctx["browser"] = None
        return None

def _extract_address(html: str) -> Optional[str]:
    """Find a property address pattern in the case detail HTML."""
    if not html:
        return None
    # Strip HTML tags for cleaner regex matching
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # Scan all matches; prefer ones that look like property descriptions
    candidates = []
    for m in ADDR_RE.finditer(text):
        addr = m.group(1).strip()
        # Skip law-firm office addresses (common false positive)
        ctx = text[max(0, m.start() - 100):m.start()].lower()
        if any(s in ctx for s in ("attorney for", "law firm", "law office",
                                   "p.o. box", "post office")):
            continue
        candidates.append(addr)
    if candidates:
        # Pick the longest match (more specific addresses are usually longer)
        return max(candidates, key=len)
    return None


def _apply_court_detail(li: Listing, html: str) -> bool:
    """Parse SC case-detail HTML for court detail (judgment, sale documents,
    sale_status) and store onto the listing — same raw fields as the NC Tyler
    path so the dashboard treats both uniformly. Returns True if anything found.

    Uses parse_sc_case_detail (selectolax table parser) for SC HTML, which
    extracts the full party roster, judgment, docket, costs, payments, and
    property info. Falls back to parse_register_of_actions (regex) for
    Tyler text pages.
    """
    from .court_detail_parser import parse_sc_case_detail, parse_register_of_actions

    # Try the SC selectolax parser first (handles both SC HTML and Tyler text)
    roa = parse_sc_case_detail(html)
    if not roa or not roa.get("parties") and not roa.get("judgment"):
        # Fallback: pure regex parser (works on Tyler text)
        roa = parse_register_of_actions(html)
    if not roa:
        return False

    if not isinstance(li.raw, dict):
        li.raw = {}

    # --- Backward-compatible fields (same as before) ---
    if roa.get("judgment_amount") and not li.judgment_amount:
        li.judgment_amount = roa["judgment_amount"]
    if roa.get("balance_due") is not None:
        li.raw["court_balance_due"] = roa["balance_due"]
        # balance_due_as_of may come from Tyler regex path
        if roa.get("balance_due_as_of"):
            li.raw["court_balance_due_as_of"] = roa["balance_due_as_of"]
    if roa.get("documents"):
        li.raw["court_documents"] = roa["documents"]
    ss = roa.get("sale_status")
    if ss:
        li.raw["court_sale_status"] = ss
        if ss == "confirmed":
            li.raw["sold_confirmed"] = True

    # --- NEW: rich structured data from SC table parser ---
    if roa.get("case_caption"):
        li.raw["court_case_caption"] = roa["case_caption"]
    if roa.get("case_number"):
        li.raw["court_case_number"] = roa["case_number"]
    if roa.get("parties"):
        li.raw["court_parties"] = roa["parties"]
    if roa.get("judgment"):
        li.raw["court_judgment"] = roa["judgment"]
    if roa.get("judgment_details"):
        li.raw["court_judgment_details"] = roa["judgment_details"]
    if roa.get("docket"):
        li.raw["court_docket"] = roa["docket"]
    if roa.get("summary"):
        li.raw["court_summary"] = roa["summary"]
    if roa.get("costs"):
        li.raw["court_costs"] = roa["costs"]
    if roa.get("payments"):
        li.raw["court_payments"] = roa["payments"]
    if roa.get("property"):
        li.raw["court_property"] = roa["property"]
        # Try to extract property address from tax_map_description
        prop = roa["property"]
        desc = prop.get("tax_map_description", "")
        if desc and not li.street_address:
            addr = _extract_address(desc)
            if addr:
                li.street_address = addr.strip()
    if roa.get("associated_cases"):
        li.raw["court_associated_cases"] = roa["associated_cases"]

    return True


async def enrich_case_detail_addresses(listings: list[Listing]) -> None:
    """Render SC case-detail pages to (a) resolve placeholder "Lis Pendens"
    addresses and (b) capture court detail (judgment / sale documents /
    sale_status — incl. the confirmed-sold flag that filters sold properties).

    Default targets: placeholder-address SC lis pendens (address resolution).
    With SC_COURT_INCREMENTAL=1: also sweep ALL SC cases with a case# that
    aren't court-enriched yet (capped by SC_COURT_CAP, default 60), so court
    coverage builds across runs like the NC pass.
    """
    import os
    incremental = os.environ.get("SC_COURT_INCREMENTAL") == "1"
    cap = int(os.environ.get("SC_COURT_CAP", "60"))

    def _placeholder(li: Listing) -> bool:
        return bool(li.street_address and li.street_address.startswith("Lis Pendens ")
                    and "lis_pendens" in (li.source or "").lower())

    def _needs_court(li: Listing) -> bool:
        r = li.raw if isinstance(li.raw, dict) else {}
        return not r.get("court_sale_status")

    seen: set[int] = set()
    targets: list[Listing] = []
    for li in listings:
        if li.state != "SC" or not li.case_number:
            continue
        if _placeholder(li) or (incremental and _needs_court(li)):
            if id(li) not in seen:
                seen.add(id(li))
                targets.append(li)
    if incremental:
        targets = targets[:cap]
    if not targets:
        log.info("case_detail.no_targets")
        return

    log.info("case_detail.start", target_count=len(targets), incremental=incremental)

    # Sequential (Semaphore 1) — ONE browser at a time on 8GB machine.
    # Old code used Semaphore(2) + asyncio.gather which could open 2 Chrome
    # instances simultaneously and spawned 2,205 coroutines at once.
    sem = asyncio.Semaphore(1)
    counts = {"queried": 0, "resolved": 0, "no_match": 0, "court_tagged": 0}

    async def one(li: Listing) -> None:
        urls = _sc_case_urls(li.case_number)
        if not urls:
            return
        # Determine county for nodriver flow
        cn = li.case_number or ""
        m = re.match(r"(\d{4})-CP-(\d{2})-(\d{4,6})", cn.strip())
        county = SC_COUNTY_BY_CODE.get(m.group(2), "") if m else ""
        async with sem:
            counts["queried"] += 1
            # Try nodriver first (if we know the county), then fall back to URL fetch
            html = await _fetch_case_detail_html(urls[0], case_number=cn, county=county)
            if not html or len(html) < 2000:
                # Try alternate URLs
                for url in urls[1:]:
                    html = await _fetch_case_detail_html(url)
                    if html and len(html) > 2000:
                        break
            if html and len(html) > 2000:
                if _apply_court_detail(li, html):
                    counts["court_tagged"] += 1
                    if not isinstance(li.raw, dict):
                        li.raw = {}
                    li.raw["court_record_url"] = urls[0]
                if li.street_address and li.street_address.startswith("Lis Pendens "):
                    addr = _extract_address(html)
                    if addr:
                        li.street_address = addr.strip()
                        counts["resolved"] += 1
                return
            counts["no_match"] += 1

    await asyncio.gather(*(one(li) for li in targets))
    await _close_browser()
    log.info("case_detail.done", **counts)
