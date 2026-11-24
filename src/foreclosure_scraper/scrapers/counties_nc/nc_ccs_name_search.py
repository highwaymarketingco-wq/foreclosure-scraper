"""NC CCS 4 Counties via name-search pattern (Caldwell, Franklin, Hertford, Gates).

Adapted from enrichment_gaston_rod.py's proven pattern.

PROBLEM: Broad date-range POST times out (Cloudflare 524 - backend can't handle it)
SOLUTION: Per-surname search using same 3-step session pattern as Gaston

Counties: Caldwell, Franklin, Hertford, Gates (NOT Cloudflare-blocked)
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from typing import AsyncGenerator

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# County subdomains
_COUNTIES = {
    "Caldwell": "caldwellnc",
    "Franklin": "franklinnc",
    "Hertford": "hertfordnc",
    "Gates": "gatesnc",
}

_BASE = "https://{subdomain}.courthousecomputersystems.com"
_LRINDEX = "/LRSearch/LRIndex?searchTabID=0"
_EXEC = "/LRSearch/ExecuteSearch"

_HDRS = {
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Distress indicators
_DISTRESS_KINDS = re.compile(
    r"\b(LIEN|JUDG|TAX|LIS\s*PEND|FORECLOS|TRUSTEE|EXECUTION|MECHANIC)\b", re.I
)

# DevExpress grid parsing (from Gaston)
_ROW = re.compile(r'<tr id="gridTrad_DXDataRow\d+"[^>]*>(.*?)</tr>', re.S)
_CELL = re.compile(r'class="[^"]*Cell_(\w+) dxgv"[^>]*>(.*?)</td>', re.S)

# Top 50 US surnames (should cover ~12% of population)
_COMMON_SURNAMES = [
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES",
    "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ",
    "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON",
    "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN",
    "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS",
    "SANCHEZ", "CLARK", "RAMIREZ", "LEWIS", "ROBINSON",
    "WALKER", "YOUNG", "ALLEN", "KING", "WRIGHT",
    "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES",
    "GREEN", "ADAMS", "NELSON", "BAKER", "HALL",
    "RIVERA", "CAMPBELL", "MITCHELL", "CARTER", "ROBERTS",
]


def _text(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _body(last: str) -> str:
    """Build POST body for surname search."""
    params = [
        "MaxRecordCount=2000",
        "PageSize=200",
        "SortOrder=1",
        "IsAdvancedSearch=true",
        "ResultsAreFiltered=false",
        "SearchWasDirectory=false",
        "SearchTabID=0",
        "LRMatchContainsDefaultOn=False",
        "allRowsAreExpanded=false",
        "SearchType=3",
        f"MultiNameLast%5B%5D={urllib.parse.quote(last)}",
        "MultiNameGiven%5B%5D=",  # Empty first name
        "MultiNameSearchType%5B%5D=3",
        "SearchRefDocs=false",
        "SimilarNameSearch=none",
        "MatchType=beginswith",
        "CodeType=3",
        "IndexType=3",
        "SymbolSetOut=false",
        "AdvancedDescriptionQualifier%5B%5D=%2B%2B",
        "AdvancedDescriptionAndOr%5B%5D=AND",
        "ResultsType=1",
        "ExpandAllRows=false",
        "HighlightSearchTermsInResults=false",
        "AutocompleteEnabled=false",
        "SortDirectionPrimary=1",
        "SortDirectionSecondary=1",
    ]
    return "&".join(params)


def _parse_rows(html: str) -> list[dict]:
    """Parse DevExpress grid into instrument dicts."""
    rows: list[dict] = []
    for rm in _ROW.finditer(html or ""):
        cells = {}
        for cm in _CELL.finditer(rm.group(1)):
            cells[cm.group(1).lower()] = _text(cm.group(2))
        if any(cells.get(k) for k in ("grantor", "grantee", "kind", "date")):
            rows.append(cells)
    return rows


def _has_distress_signal(row: dict) -> bool:
    """Check if instrument row indicates distress."""
    kind = row.get("kind", "")
    desc = row.get("description", "")
    blob = f"{kind} {desc}"
    return bool(_DISTRESS_KINDS.search(blob))


async def _seed_and_search(
    client: httpx.AsyncClient,
    base: str,
    surname: str
) -> list[dict]:
    """3-step session + search, return distress instruments."""
    try:
        # Step 1: GET / for session cookie
        await client.get(base, follow_redirects=True)
        
        # Step 2: Seed search context
        lrindex_url = base + _LRINDEX
        resp = await client.get(lrindex_url)
        
        if resp.status_code != 200:
            log.warning("ccs_name.seed_failed", base=base, status=resp.status_code)
            return []
        
        # Step 3: Execute search
        exec_url = base + _EXEC
        headers = {**_HDRS, "Referer": lrindex_url}
        body = _body(surname)
        
        resp = await client.post(exec_url, content=body, headers=headers)
        
        if resp.status_code != 200:
            log.warning("ccs_name.search_failed", surname=surname, status=resp.status_code)
            return []
        
        # Parse and filter
        all_rows = _parse_rows(resp.text)
        distress_rows = [r for r in all_rows if _has_distress_signal(r)]
        
        if distress_rows:
            log.info("ccs_name.distress_found", surname=surname, 
                    total=len(all_rows), distress=len(distress_rows))
        
        return distress_rows
        
    except Exception as exc:
        log.error("ccs_name.exception", surname=surname, error=str(exc)[:200])
        return []


class NcCcsNameSearchScraper(BaseScraper):
    """NC CCS 4 counties via per-surname discovery."""
    
    slug = "counties_nc.nc_ccs_name_search"
    name = "NC CCS Name Search (4 counties)"
    category = "rod"
    timeout_s = 1800.0  # 30 min for all counties
    
    async def fetch(self) -> list[Listing]:
        """Search each county × common surnames for distress signals."""
        
        results: list[Listing] = []
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for county, subdomain in _COUNTIES.items():
                base = _BASE.format(subdomain=subdomain)
                county_instruments: list[dict] = []
                
                log.info("ccs_name.county_start", county=county)
                
                for surname in _COMMON_SURNAMES:
                    instruments = await _seed_and_search(client, base, surname)
                    county_instruments.extend(instruments)
                
                # Dedupe by doc number within county
                seen = set()
                unique_instruments = []
                for instr in county_instruments:
                    doc_no = instr.get("docno", "")
                    if doc_no and doc_no not in seen:
                        seen.add(doc_no)
                        unique_instruments.append(instr)
                
                log.info("ccs_name.county_done", county=county, 
                        total=len(county_instruments), unique=len(unique_instruments))
                
                # Convert to Listings
                for instr in unique_instruments:
                    # Extract address from description if present
                    desc = instr.get("description", "")
                    addr_match = re.search(
                        r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:St|Ave|Dr|Rd|Ln|Way|Ct|Blvd))?",
                        desc
                    )
                    street_address = addr_match.group(0) if addr_match else None
                    
                    # Determine listing type from kind/description
                    kind = instr.get("kind", "").upper()
                    if "LIS" in kind or "LIS PEND" in desc.upper():
                        listing_type = ListingType.LIS_PENDENS
                    elif "LIEN" in kind or "LIEN" in desc.upper():
                        listing_type = ListingType.TAX_LIEN
                    elif "JUDG" in kind:
                        listing_type = ListingType.LIEN_CLAIM
                    else:
                        listing_type = ListingType.UNKNOWN
                    
                    results.append(Listing(
                        source=self.slug,
                        listing_type=listing_type,
                        property_kind=PropertyKind.UNKNOWN,
                        county=county,
                        state="NC",
                        street_address=street_address,
                        source_url=base + "/LRSearch",
                        raw={
                            "kind": instr.get("kind"),
                            "date": instr.get("date"),
                            "grantor": instr.get("grantor"),
                            "grantee": instr.get("grantee"),
                            "description": desc[:500],
                            "doc_no": instr.get("docno"),
                            "book": instr.get("book"),
                            "page": instr.get("page"),
                        },
                    ))
        
        return results
