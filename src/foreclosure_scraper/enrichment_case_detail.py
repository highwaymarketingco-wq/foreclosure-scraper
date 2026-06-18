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


async def _fetch_case_detail_html(url: str) -> Optional[str]:
    """Render the case detail page via Scrapling stealth."""
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
    path so the dashboard treats both uniformly. Returns True if anything found."""
    from .court_detail_parser import parse_register_of_actions
    roa = parse_register_of_actions(html)
    if not roa:
        return False
    if not isinstance(li.raw, dict):
        li.raw = {}
    if roa.get("judgment_amount") and not li.judgment_amount:
        li.judgment_amount = roa["judgment_amount"]
    if roa.get("balance_due"):
        li.raw["court_balance_due"] = roa["balance_due"]
        li.raw["court_balance_due_as_of"] = roa.get("balance_due_as_of")
    if roa.get("documents"):
        li.raw["court_documents"] = roa["documents"]
    ss = roa.get("sale_status")
    if ss:
        li.raw["court_sale_status"] = ss
        if ss == "confirmed":
            li.raw["sold_confirmed"] = True
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

    sem = asyncio.Semaphore(2)
    counts = {"queried": 0, "resolved": 0, "no_match": 0, "court_tagged": 0}

    async def one(li: Listing) -> None:
        urls = _sc_case_urls(li.case_number)
        if not urls:
            return
        async with sem:
            counts["queried"] += 1
            for url in urls:
                html = await _fetch_case_detail_html(url)
                if html and len(html) > 2000:
                    if _apply_court_detail(li, html):
                        counts["court_tagged"] += 1
                        if not isinstance(li.raw, dict):
                            li.raw = {}
                        li.raw["court_record_url"] = url
                    if li.street_address and li.street_address.startswith("Lis Pendens "):
                        addr = _extract_address(html)
                        if addr:
                            li.street_address = addr.strip()
                            counts["resolved"] += 1
                    return
            counts["no_match"] += 1

    await asyncio.gather(*(one(li) for li in targets))
    log.info("case_detail.done", **counts)
