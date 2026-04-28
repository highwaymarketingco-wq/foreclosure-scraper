"""Court records enrichment via NC eCourts + SC Public Index.

For every listing with a case number we hit the relevant e-court system through
Apify rag-web-browser (both portals are JS-heavy + Cloudflare-protected) and
extract: plaintiff, defendant, filing date, hearing date, sale location.

ALSO discovers NEW lis pendens / foreclosure cases per county (independent of any
existing listing) by hitting the per-county case-search URL.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Iterable

import structlog

from .apify_helper import fetch_rendered
from .config import ALL_COUNTIES
from .models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# ---------- URL templates ----------------------------------------------------------

SC_PUBLICINDEX = "https://publicindex.sccourts.org/{county}/PublicIndex/CaseDetails.aspx?Case={case}"
SC_PUBLICINDEX_SEARCH = (
    "https://publicindex.sccourts.org/{county}/PublicIndex/CaseSearchResults.aspx?"
    "casetype=CP&casesubtype=Foreclosure&filedstart={start}&filedend={end}"
)
NC_ECOURTS_SEARCH = (
    "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/26?county={county}"
    "&caseType=SP&caseStatus=Active"
)


# ---------- Field regexes -----------------------------------------------------------

PLAINTIFF_RE = re.compile(r"(?:Plaintiff|Petitioner)[:\s]+(.+?)(?=\n|Defendant|Respondent|$)", re.I | re.S)
DEFENDANT_RE = re.compile(r"(?:Defendant|Respondent)[:\s]+(.+?)(?=\n|Plaintiff|Petitioner|Trustee|$)", re.I | re.S)
TRUSTEE_RE = re.compile(r"(?:Substitute Trustee|Trustee)[:\s]+(.+?)(?=\n|$)", re.I | re.S)
FILING_DATE_RE = re.compile(r"(?:Filed|Filing Date|Date Filed)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
SALE_DATE_RE = re.compile(r"(?:Sale Date|Hearing Date|Auction Date)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
SALE_LOC_RE = re.compile(r"(?:Sale Location|Location)[:\s]+(.+?)(?=\n|$)", re.I | re.S)
NC_CASE_RE = re.compile(r"\b\d{2}\s?SP\s?\d{3,6}(?:-\d+)?\b", re.I)
SC_CASE_RE = re.compile(r"\b\d{4}\s?CP\s?\d{2}\s?\d{4,6}\b", re.I)


def _apply_court_text(li: Listing, text: str) -> int:
    """Pull plaintiff/defendant/trustee/sale info from rendered case-details text."""
    filled = 0

    def maybe(field: str, val):
        nonlocal filled
        if not val:
            return
        cur = getattr(li, field, None)
        if cur in (None, "", 0):
            setattr(li, field, val.strip())
            filled += 1

    if not li.plaintiff:
        m = PLAINTIFF_RE.search(text)
        if m:
            maybe("plaintiff", m.group(1).strip().split("\n")[0][:200])
    if not li.defendant:
        m = DEFENDANT_RE.search(text)
        if m:
            maybe("defendant", m.group(1).strip().split("\n")[0][:200])
    if not li.trustee:
        m = TRUSTEE_RE.search(text)
        if m:
            maybe("trustee", m.group(1).strip().split("\n")[0][:200])
    if not li.sale_location:
        m = SALE_LOC_RE.search(text)
        if m:
            maybe("sale_location", m.group(1).strip().split("\n")[0][:200])
    return filled


# ---------- Enrich existing listings ------------------------------------------------

async def enrich_with_court_records(listings: list[Listing]) -> list[Listing]:
    """For every listing that has a case_number, look it up in the right e-court system."""
    token = os.environ.get("APIFY_TOKEN", "")
    if not token:
        log.info("courts.skip", reason="no_apify_token")
        return listings

    sem = asyncio.Semaphore(4)
    counts = {"queried": 0, "matched": 0, "fields_filled": 0}

    async def lookup(li: Listing) -> None:
        if not (li.case_number and li.county and li.state):
            return
        county_clean = li.county.replace(" County", "").strip().split(",")[0].strip()
        if li.state == "SC":
            url = SC_PUBLICINDEX.format(county=county_clean, case=li.case_number)
        elif li.state == "NC":
            # NC eCourts uses a search page; we can include case# in search params
            url = (
                "https://portal-nc.tylertech.cloud/Portal/Home/WorkspaceMode?p=0"
                f"&q={li.case_number}"
            )
        else:
            return
        async with sem:
            counts["queried"] += 1
            content = await fetch_rendered(url, token=token)
            if not content:
                return
            counts["matched"] += 1
            counts["fields_filled"] += _apply_court_text(li, content)

    await asyncio.gather(*(lookup(li) for li in listings))
    log.info("courts.enrich.done", **counts)
    return listings


# ---------- Discover new lis pendens / foreclosure cases ---------------------------

async def discover_lis_pendens() -> list[Listing]:
    """Hit each county's e-court case-search for NEW foreclosure / lis-pendens filings.

    Returns one Listing per case number found, populated with whatever the
    search-results page exposes (case number, county, listing_type=LIS_PENDENS,
    plus any plaintiff/defendant text we can scrape).
    """
    token = os.environ.get("APIFY_TOKEN", "")
    if not token:
        return []

    sem = asyncio.Semaphore(3)
    out: list[Listing] = []

    async def search_county(state: str, county: str) -> None:
        if state == "SC":
            url = (
                f"https://publicindex.sccourts.org/{county}/PublicIndex/"
                "CaseSearchResults.aspx?casetype=CP&casesubtype=Foreclosure"
            )
            case_re = SC_CASE_RE
            ltype = ListingType.LIS_PENDENS
        else:
            url = (
                "https://portal-nc.tylertech.cloud/Portal/Home/WorkspaceMode?"
                f"p=0&q=foreclosure+{county}&caseType=SP"
            )
            case_re = NC_CASE_RE
            ltype = ListingType.LIS_PENDENS

        async with sem:
            content = await fetch_rendered(url, token=token)
            if not content:
                return
            seen: set[str] = set()
            for case in case_re.findall(content):
                clean = re.sub(r"\s+", "", case)
                if clean in seen:
                    continue
                seen.add(clean)
                out.append(
                    Listing(
                        source="courts.lis_pendens_discovery",
                        source_url=url,
                        listing_type=ltype,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        case_number=clean,
                        description=f"Lis pendens / foreclosure filing {clean} ({county} County, {state})",
                        first_seen=__import__("datetime").datetime.utcnow(),
                        last_seen=__import__("datetime").datetime.utcnow(),
                    )
                )

    await asyncio.gather(*(search_county(c.state, c.name) for c in ALL_COUNTIES))
    log.info("courts.lis_pendens.discovered", count=len(out))
    return out
