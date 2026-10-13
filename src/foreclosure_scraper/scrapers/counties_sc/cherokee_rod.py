"""Cherokee County SC Register of Deeds via Avenu/GRIDS platform.

STATUS (re-verified live 2026-10-13): WORKING with login credentials.

The real site is https://cherokeesc.avenuinsights.com — the GRIDS Land
Records System. Login with credentials stored in:
  - .secrets/cherokee_sc/email.txt
  - .secrets/cherokee_sc/password.txt

Search capabilities (all confirmed working):
  - Party name search (grantor/grantee)
  - Date range search (StartDate / EndDate)
  - Parcel ID search (ParcelId)
  - Address search (StreetNumber / StreetName / City)
  - Book/Page lookup
  - Case number search
  - Details endpoint: /Public/cherokeesc/InstrumentGrid/Details?InstrumentID=

The old sclandrecords.com URL 404s — this file replaces it entirely.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://cherokeesc.avenuinsights.com"
_LOGIN_URL = f"{_BASE}/Public/cherokeesc/Account/Login"
_SEARCH_URL = f"{_BASE}/Public/cherokeesc/InstrumentGrid/Search"
_GRID_URL = f"{_BASE}/Public/cherokeesc/InstrumentGrid"
_DETAILS_URL = f"{_BASE}/Public/cherokeesc/InstrumentGrid/Details"

_SECRETS_DIR = Path(__file__).resolve().parents[4] / ".secrets" / "cherokee_sc"

# Lien/mortgage document types to flag during enrichment
_LIEN_DOCTYPES = {
    "SATISFACTION", "RELEASE", "LIEN", "MORTGAGE", "DEED OF TRUST",
    "MECHANICS LIEN", "JUDGMENT", "LIS PENDENS",
}

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _load_credentials() -> tuple[str, str]:
    """Read email/password from secrets directory."""
    email_path = _SECRETS_DIR / "email.txt"
    pass_path = _SECRETS_DIR / "password.txt"
    if not email_path.exists() or not pass_path.exists():
        raise FileNotFoundError(
            f"Cherokee ROD credentials not found at {_SECRETS_DIR}. "
            "Expected email.txt and password.txt."
        )
    email = email_path.read_text().strip()
    password = pass_path.read_text().strip()
    return email, password


async def _login(client: httpx.AsyncClient) -> bool:
    """Login to the GRIDS platform. Returns True on success."""
    headers = {"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"}
    
    # GET login page for antiforgery token
    r = await client.get(_LOGIN_URL, headers=headers, follow_redirects=True)
    if r.status_code != 200:
        log.error("cherokee_rod.login_page_fail", status=r.status_code)
        return False
    
    tree = HTMLParser(r.text)
    token = ""
    for inp in tree.css("input"):
        if inp.attributes.get("name") == "__RequestVerificationToken":
            token = inp.attributes.get("value", "")
    
    email, password = _load_credentials()
    
    # POST login
    r2 = await client.post(
        _LOGIN_URL,
        data={
            "__RequestVerificationToken": token,
            "Email": email,
            "Password": password,
        },
        headers={
            **headers,
            "Referer": _LOGIN_URL,
            "Origin": _BASE,
        },
        follow_redirects=True,
    )
    
    # Success: we land on InstrumentGrid, not Login
    if "/Account/Login" in str(r2.url):
        log.error("cherokee_rod.login_failed", url=str(r2.url))
        return False
    
    log.info("cherokee_rod.login_ok", url=str(r2.url))
    return True


async def _search_by_name(
    client: httpx.AsyncClient,
    name: str,
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Search instruments by party name. Returns list of instrument dicts.
    
    Dates in MM/DD/YYYY format.
    Uses GET to /InstrumentGrid/Search which returns JSON with a "search"
    object containing a "Names" array of instrument records.
    
    SearchCriteria values:
      1=Grantors, 2=Grantees, 3=Grantors & Grantees,
      4=Instrument#, 5=Recorded Date, 6=Book & Page,
      7=Instrument Type, 8=Property
    """
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": _GRID_URL,
    }
    
    params = {
        "Name": name,
        "SearchCriteria": "3",  # Grantors & Grantees
        "SearchType": "S",
    }
    if start_date:
        params["StartDate"] = start_date
    if end_date:
        params["EndDate"] = end_date
    
    r = await client.get(_SEARCH_URL, params=params, headers=headers)
    
    if r.status_code != 200:
        log.warning("cherokee_rod.search_fail", status=r.status_code)
        return []
    
    try:
        j = r.json()
    except Exception:
        log.warning("cherokee_rod.search_not_json", status=r.status_code, size=len(r.text))
        return []
    
    if j.get("status") != "Success":
        log.warning("cherokee_rod.search_bad_status", status=j.get("status"))
        return []
    
    search_obj = j.get("search", {})
    if isinstance(search_obj, dict):
        results = search_obj.get("Names", [])
    else:
        results = []
    
    log.info("cherokee_rod.search_results", name=name, count=len(results))
    return results


async def _get_details(
    client: httpx.AsyncClient,
    instrument_id: str,
) -> dict | None:
    """Get full instrument details by InstrumentID."""
    r = await client.get(
        f"{_DETAILS_URL}",
        params={"InstrumentID": instrument_id},
        headers={
            "User-Agent": _UA,
            "Accept": "text/html",
            "Referer": _GRID_URL,
        },
    )
    
    if r.status_code != 200:
        return None
    
    tree = HTMLParser(r.text)
    
    details = {"instrument_id": instrument_id}
    
    # Parse the details page — look for labeled fields
    for row in tree.css("tr, .detail-row, .form-group"):
        cells = row.css("td, th, label, .label, .value")
        if len(cells) >= 2:
            key = cells[0].text().strip()
            val = cells[1].text().strip()
            if key and val and len(key) < 50:
                details[key.lower().replace(" ", "_")] = val
    
    # Also extract all text for keyword matching
    body_text = tree.body.text(separator="\n") if tree.body else ""
    details["_full_text"] = body_text[:5000]
    
    return details


class CherokeeSCROD(BaseScraper):
    """Cherokee County SC ROD via Avenu/GRIDS platform.
    
    Enrichment-only: called by the ROD enrichment pipeline. Standalone fetch
    returns []. Use search_owner() or search_parcel() for lookups.
    """
    slug = "counties_sc.cherokee_rod"
    name = "Cherokee County SC Register of Deeds (Avenu/GRIDS)"
    category = "rod_enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return []

    @staticmethod
    async def search_owner(owner_name: str) -> dict | None:
        """Search Cherokee County SC ROD for filings by owner name.
        
        Returns dict with lien/mortgage info or None if not found.
        Credentials auto-loaded from .secrets/cherokee_sc/.
        """
        if not owner_name or len(owner_name.strip()) < 3:
            return None

        # Split "Last, First" -> search terms
        parts = owner_name.split(",", 1)
        last = parts[0].strip() if parts else owner_name.strip()
        first = parts[1].strip() if len(parts) > 1 else ""
        search_name = f"{last}, {first}" if first else last

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=60.0
        ) as c:
            if not await _login(c):
                return None

            results = await _search_by_name(c, search_name)
            if not results:
                # Try just last name
                results = await _search_by_name(c, last)

            if not results:
                return None

            # Analyze results for lien indicators
            has_mortgage = False
            has_lien = False
            has_satisfaction = False
            filings: list[dict] = []

            for item in results:
                # Build text from key fields for keyword matching
                kind = (item.get("Kind") or "").upper()
                index_name = (item.get("IndexName") or "").upper()
                direct = (item.get("DirectName") or "").upper()
                indirect = (item.get("IndirectName") or "").upper()
                text = f"{kind} {index_name} {direct} {indirect}"

                doc_type = None
                for dt in _LIEN_DOCTYPES:
                    if dt in text:
                        doc_type = dt.strip()
                        break
                if doc_type:
                    if "MORTGAGE" in text or "DEED OF TRUST" in text:
                        has_mortgage = True
                    if "LIEN" in text:
                        has_lien = True
                    if "SATISFACTION" in text or "RELEASE" in text:
                        has_satisfaction = True

                filing = {
                    "doc_type": doc_type or kind,
                    "instrument_id": item.get("InstrumentID", ""),
                    "instrument_date": item.get("InstrumentDateAsString", ""),
                    "book": item.get("Book", ""),
                    "volume": item.get("Volume", ""),
                    "page": item.get("Page", ""),
                    "kind": kind,
                    "direct_name": item.get("DirectName", ""),
                    "indirect_name": item.get("IndirectName", ""),
                    "consideration": item.get("Consideration", ""),
                    "description": item.get("Description", ""),
                    "act": item.get("Act", ""),
                }
                filings.append(filing)

            # Fetch details for first few instruments
            detailed_filings = []
            for f in filings[:10]:
                iid = f.get("instrument_id", "")
                if iid:
                    details = await _get_details(c, str(iid))
                    if details:
                        f["details"] = details
                detailed_filings.append(f)

            return {
                "owner_name": owner_name,
                "has_mortgage": has_mortgage,
                "has_lien": has_lien,
                "has_satisfaction": has_satisfaction,
                "filing_count": len(filings),
                "filings": detailed_filings[:20],
                "url": _GRID_URL,
            }

    @staticmethod
    async def search_parcel(parcel_id: str) -> dict | None:
        """Search Cherokee County SC ROD by parcel ID.
        
        Uses SearchCriteria=8 (Property) to search by parcel.
        """
        if not parcel_id or len(parcel_id.strip()) < 3:
            return None

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=60.0
        ) as c:
            if not await _login(c):
                return None

            headers = {
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": _GRID_URL,
            }

            # SearchCriteria=8 is "Property" search
            r = await c.get(_SEARCH_URL, params={
                "ParcelId": parcel_id,
                "SearchCriteria": "8",
                "SearchType": "S",
            }, headers=headers)

            try:
                j = r.json()
            except Exception:
                log.warning("cherokee_rod.parcel_not_json", status=r.status_code)
                return None

            if j.get("status") != "Success":
                log.warning("cherokee_rod.parcel_bad_status", status=j.get("status"))
                return None

            search_obj = j.get("search", {})
            if isinstance(search_obj, dict):
                results = search_obj.get("Names", [])
            else:
                results = []

            log.info("cherokee_rod.parcel_search", parcel=parcel_id, count=len(results))

            if not results:
                return None

            return {
                "parcel_id": parcel_id,
                "instrument_count": len(results),
                "instruments": [
                    {
                        "instrument_id": r.get("InstrumentID", ""),
                        "kind": r.get("Kind", ""),
                        "date": r.get("InstrumentDateAsString", ""),
                        "direct_name": r.get("DirectName", ""),
                        "indirect_name": r.get("IndirectName", ""),
                        "consideration": r.get("Consideration", ""),
                        "book": r.get("Book", ""),
                        "volume": r.get("Volume", ""),
                        "page": r.get("Page", ""),
                    }
                    for r in results[:50]
                ],
                "url": _GRID_URL,
            }
