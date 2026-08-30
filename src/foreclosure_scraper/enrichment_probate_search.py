"""Probate court case search for deceased/inherited property owners.

When enrichment_life_events flags an owner as "estate_probate" (HEIRS, ESTATE OF,
ESTATE in the owner name), this enricher searches the relevant probate court
system to find the actual probate case — case number, filing date, executor/
personal representative, and property disposition.

NC: eCourts (Tyler Odyssey) — search by deceased party name + county.
    URL: https://www1.nccourts.org/onlineservices/enquiry/cr/cr_enquiry.php
    (But NC probate is handled by Clerk of Superior Court in each county)

SC: Probate Court case search via publicindex.sccourts.org or county-specific
    probate court portals.

Free, uses Scrapling stealth (anti-bot bypass), no auth.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()

CONCURRENCY = int(os.environ.get("PROBATE_CONCURRENCY", "2"))
FETCH_TIMEOUT = float(os.environ.get("PROBATE_TIMEOUT_S", "45"))
MAX_LOOKUPS = int(os.environ.get("PROBATE_MAX_LOOKUPS", "200"))

# NC counties served by eCourts Tyler Odyssey (most NC counties by 2026)
# Probate = "Estate" case type in NC eCourts
NC_ESTATE_CASE_TYPES = {"ESP": "Estate Special Proceedings", "EST": "Estate"}

# SC probate court county codes for publicindex.sccourts.org
SC_PROBATE_COUNTY_CODES = {
    "Anderson": "04", "Cherokee": "11", "Pickens": "39", "Spartanburg": "42",
    "Oconee": "37", "York": "46", "Greenville": "23", "Laurens": "30",
    "Union": "44", "Bamberg": "07",
}

_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "DDS", "ESQ"}
_TRUST_INDICATORS = re.compile(
    r"\bHEIRS?\b|\bEST(?:ATE)?\s+OF\b|\bESTATE\b|\bPROBATE\b|\bDECEDENT\b",
    re.I,
)


def _is_probate_candidate(li: Listing) -> bool:
    """Only search for listings where owner name signals probate/estate."""
    if not isinstance(li.raw, dict):
        return False
    # Check life_events flag
    life = li.raw.get("life_events")
    if isinstance(life, list) and "estate_probate" in life:
        return True
    # Check owner name directly
    owner = _best_owner(li)
    if owner and _TRUST_INDICATORS.search(owner):
        return True
    return False


def _best_owner(li: Listing) -> str | None:
    """Best owner name for probate matching."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    gis = raw.get("gis") or {}
    if isinstance(gis, dict):
        owner = gis.get("owner")
        if owner:
            return owner
    return getattr(li, "defendant", None) or getattr(li, "owner_name", None)


def _extract_decedent_name(owner: str) -> str:
    """Extract the decedent's actual name from 'ESTATE OF JOHN SMITH' etc."""
    name = re.sub(r"\bEST(?:ATE)?\s+OF\b", "", owner, flags=re.I)
    name = re.sub(r"\bHEIRS?\s+OF\b", "", name, flags=re.I)
    name = re.sub(r"\bTRUSTEE\b|\bTR\b", "", name, flags=re.I)
    name = re.sub(r"\bET\s+AL\b", "", name, flags=re.I)
    # Strip trust language
    name = re.sub(r"\bTRUST\b.*$", "", name, flags=re.I)
    return name.strip()


async def _sc_probate_search(
    county: str, decedent_name: str
) -> list[dict]:
    """Search SC Probate Court cases on publicindex.sccourts.org.

    Uses Scrapling StealthyFetcher to bypass F5 BIG-IP anti-bot.
    Returns list of {case_number, filing_date, decedent, personal_rep, status}.
    """
    county_code = SC_PROBATE_COUNTY_CODES.get(county)
    if not county_code:
        return []

    # Build the probate search URL
    base = f"https://publicindex.sccourts.org/{county}/PublicIndex/"
    # SC probate cases start with the year + county + PG (probate general) or PF (formal)
    search_url = (
        f"{base}CaseDetails.aspx?CaseNum={decedent_name.replace(' ', '+')}"
        f"&Type=Probate"
    )

    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector("table, body, .DataGrid", timeout=15000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        result = await asyncio.wait_for(
            StealthyFetcher.async_fetch(
                search_url, headless=True, network_idle=True,
                timeout=int(FETCH_TIMEOUT), page_action=page_action,
            ),
            timeout=FETCH_TIMEOUT + 15,
        )
    except (asyncio.TimeoutError, Exception):
        return []

    html = getattr(result, "body", b"")
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    html = str(html or "")

    if len(html) < 1000:
        return []

    # Parse case results from HTML table
    cases: list[dict] = []
    # Look for case number patterns
    for m in re.finditer(
        r"(\d{4}-[A-Z]{2}-\d{2}-\d{4,6})", html
    ):
        case_num = m.group(1)
        # Grab surrounding context for filing date and party info
        ctx = html[max(0, m.start() - 200):m.end() + 500]
        ctx_text = re.sub(r"<[^>]+>", " ", ctx)
        ctx_text = re.sub(r"\s+", " ", ctx_text).strip()

        # Extract date
        date_match = re.search(
            r"(\d{1,2}/\d{1,2}/\d{4})", ctx_text
        )
        cases.append({
            "case_number": case_num,
            "filing_date": date_match.group(1) if date_match else None,
            "raw_text": ctx_text[:500],
        })

    return cases


async def _nc_probate_search(
    county: str, decedent_name: str
) -> list[dict]:
    """Search NC eCourts (Tyler Odyssey) for estate cases.

    NC eCourts requires navigating to the county's case inquiry page.
    Uses Scrapling stealth to bypass anti-bot.
    """
    # NC eCourts case search URL pattern
    # https://www1.nccourts.org/onlineservices/enquiry/cr/cr_enquiry.php
    # But the actual Tyler Odyssey portal is at:
    # https://portal.nccourts.org/Org/Extranet/Default.jsp?courtID=<county>
    # We'll try the public search endpoint
    search_url = (
        "https://www1.nccourts.org/onlineservices/enquiry/sp/sp_enquiry.php"
    )

    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            # Fill in the name search form
            last_name = decedent_name.split()[-1] if " " in decedent_name else decedent_name
            first_name = decedent_name.split()[0] if " " in decedent_name else ""
            # Try to fill the form fields
            try:
                await page.fill("input[name='redactedName'], input[name='lastName']", last_name)
                if first_name:
                    await page.fill("input[name='firstName']", first_name)
                await page.select_option("select[name='caseType']", "ESP")
            except Exception:
                pass
            await page.click("input[type='submit'], button[type='submit']")
            await page.wait_for_selector("table, .CaseInfo, .SearchResults", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    try:
        result = await asyncio.wait_for(
            StealthyFetcher.async_fetch(
                search_url, headless=True, network_idle=True,
                timeout=int(FETCH_TIMEOUT), page_action=page_action,
            ),
            timeout=FETCH_TIMEOUT + 15,
        )
    except (asyncio.TimeoutError, Exception):
        return []

    html = getattr(result, "body", b"")
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    html = str(html or "")

    if len(html) < 1000:
        return []

    # Parse NC eCourts case results
    cases: list[dict] = []
    for m in re.finditer(r"(\d{2}\s+[A-Z]{2}\s+\d{3,6})", html):
        case_num = m.group(1)
        ctx = html[max(0, m.start() - 200):m.end() + 500]
        ctx_text = re.sub(r"<[^>]+>", " ", ctx)
        ctx_text = re.sub(r"\s+", " ", ctx_text).strip()
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", ctx_text)
        cases.append({
            "case_number": case_num,
            "filing_date": date_match.group(1) if date_match else None,
            "raw_text": ctx_text[:500],
        })

    return cases


async def enrich_probate_search(listings: list[Listing]) -> dict:
    """Search probate courts for deceased/estate property owners.

    Targets listings flagged by enrichment_life_events (estate_probate flag)
    or with owner names containing ESTATE OF / HEIRS / DECEDENT.

    Writes raw['probate'] with case_number, filing_date, court, status.
    """
    eligible = [li for li in listings if _is_probate_candidate(li)]

    if len(eligible) > MAX_LOOKUPS:
        eligible = eligible[:MAX_LOOKUPS]

    if not eligible:
        log.info("probate.no_eligible")
        return {"searched": 0, "matched": 0, "eligible": 0}

    log.info("probate.start", eligible=len(eligible), max_lookups=MAX_LOOKUPS)
    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"searched": 0, "matched": 0, "eligible": len(eligible)}

    async def one(li: Listing) -> None:
        owner = _best_owner(li)
        if not owner:
            return
        decedent = _extract_decedent_name(owner)
        if len(decedent.split()) < 2:
            return

        county = (li.county or "").strip()
        state = li.state or ""

        async with sem:
            stats["searched"] += 1
            if state == "SC":
                results = await _sc_probate_search(county, decedent)
            elif state == "NC":
                results = await _nc_probate_search(county, decedent)
            else:
                return

        if not results:
            return

        # Store the first match
        case = results[0]
        li.raw.setdefault("probate", {})
        li.raw["probate"] = {
            "case_number": case.get("case_number"),
            "filing_date": case.get("filing_date"),
            "court": f"{county} County Probate Court",
            "state": state,
            "decedent": decedent,
            "status": "open" if "open" in case.get("raw_text", "").lower() else "unknown",
            "raw_text": case.get("raw_text"),
            "case_count": len(results),
        }
        stats["matched"] += 1

    await asyncio.gather(*(one(li) for li in eligible))

    log.info("probate.done", **stats)
    return stats
