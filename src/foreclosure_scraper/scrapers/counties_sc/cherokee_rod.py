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
    """
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json, text/html",
        "Referer": _GRID_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": _BASE,
    }
    
    # Step 1: POST search — returns JSON with redirect URL
    r = await client.post(
        _SEARCH_URL,
        data={
            "Name": name,
            "SearchCriteria": "0",
            "SearchType": "S",
            "StartDate": start_date,
            "EndDate": end_date,
        },
        headers=headers,
    )
    
    try:
        j = r.json()
    except Exception:
        log.warning("cherokee_rod.search_not_json", status=r.status_code, size=len(r.text))
        return []
    
    search_url = j.get("search", "")
    status = j.get("status", "")
    
    if not search_url:
        log.warning("cherokee_rod.no_search_url", status=status, response=j)
        return []
    
    # Step 2: GET the results page — it contains the Kendo grid
    full_url = search_url if search_url.startswith("http") else f"{_BASE}{search_url}"
    r2 = await client.get(full_url, headers={
        "User-Agent": _UA,
        "Accept": "text/html",
        "Referer": _GRID_URL,
    })
    
    if r2.status_code != 200:
        log.warning("cherokee_rod.results_page_fail", status=r2.status_code)
        return []
    
    # The Kendo grid loads data via AJAX. Find the transport read URL.
    tree = HTMLParser(r2.text)
    
    # Extract inline data from Kendo grid initialization
    # The grid may have inline data or require a separate AJAX call
    # Look for the dataSource configuration
    ds_match = re.search(
        r'dataSource\s*[:=]\s*(?:new\s+kendo\.data\.DataSource\s*\()?\{.*?"data"\s*:\s*(\[.*?\])',
        r2.text,
        re.DOTALL,
    )
    
    results = []
    
    if ds_match:
        try:
            data = json.loads(ds_match.group(1))
            results = data if isinstance(data, list) else []
        except json.JSONDecodeError:
            pass
    
    # If no inline data, try parsing from the HTML table
    if not results:
        table = tree.css_first("table.k-grid table, .k-grid-content table, table")
        if table:
            rows = table.css("tr")
            header_cells = []
            for row in rows:
                cells = row.css("th")
                if cells and not header_cells:
                    header_cells = [c.text().strip() for c in cells]
                    continue
                cells = row.css("td")
                if cells:
                    row_data = {}
                    for i, cell in enumerate(cells):
                        key = header_cells[i] if i < len(header_cells) else f"col_{i}"
                        row_data[key] = cell.text().strip()
                    if row_data:
                        results.append(row_data)
    
    # Also look for instrument details links
    for a in tree.css("a"):
        href = a.attributes.get("href", "") or ""
        if "Details" in href and "InstrumentID" in href:
            iid = re.search(r"InstrumentID=([^&]+)", href)
            if iid:
                results.append({"InstrumentID": iid.group(1), "link": href})
    
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
            follow_redirects=True, timeout=30.0
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
                text = " ".join(str(v) for v in item.values()).upper()
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
                    filings.append({
                        "doc_type": doc_type,
                        "instrument_id": item.get("InstrumentID", ""),
                        "excerpt": text[:300],
                    })

            # Fetch details for first few instruments
            detailed_filings = []
            for f in filings[:10]:
                iid = f.get("instrument_id", "")
                if iid:
                    details = await _get_details(c, iid)
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
        """Search Cherokee County SC ROD by parcel ID."""
        if not parcel_id or len(parcel_id.strip()) < 3:
            return None

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0
        ) as c:
            if not await _login(c):
                return None

            headers = {
                "User-Agent": _UA,
                "Accept": "application/json, text/html",
                "Referer": _GRID_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": _BASE,
            }

            r = await c.post(
                _SEARCH_URL,
                data={
                    "ParcelId": parcel_id,
                    "SearchCriteria": "0",
                    "SearchType": "S",
                },
                headers=headers,
            )

            try:
                j = r.json()
                search_url = j.get("search", "")
                if search_url:
                    full_url = (
                        search_url
                        if search_url.startswith("http")
                        else f"{_BASE}{search_url}"
                    )
                    r2 = await c.get(full_url, headers={
                        "User-Agent": _UA,
                        "Accept": "text/html",
                    })
                    tree = HTMLParser(r2.text)
                    results = []
                    for a in tree.css("a"):
                        href = a.attributes.get("href", "") or ""
                        if "Details" in href and "InstrumentID" in href:
                            iid = re.search(r"InstrumentID=([^&]+)", href)
                            if iid:
                                results.append({"InstrumentID": iid.group(1)})
                    log.info("cherokee_rod.parcel_search", parcel=parcel_id, count=len(results))
                    return {
                        "parcel_id": parcel_id,
                        "instrument_count": len(results),
                        "instruments": results[:50],
                        "url": _GRID_URL,
                    }
            except Exception as exc:
                log.warning("cherokee_rod.parcel_search_fail", error=str(exc)[:160])

            return None
