"""SC Avenu Insights ROD — Williamsburg, Kershaw, Newberry counties.

Platform: https://{county}sc.avenuinsights.com
Covers: williamsburg, kershaw, newberry (17,344 rows total)

Login required (ASP.NET MVC + __RequestVerificationToken CSRF).
Credentials: .secrets/avenu_insights/email.txt + password.txt

After login, /Public/{county}sc/InstrumentGrid provides a Kendo Grid interface.
The grid initially loads empty; data is populated via a "Search" form submission
that persists search criteria in the session, then the grid reads from that state.

The platform requires a two-step flow:
1. POST to /Search with date range + index types → stores search in session
2. Grid then loads data from the stored search state

Distress-related indices we search:
- DEED (IndexID=1): Foreclosure deeds, sheriff deeds, etc.
- MORTGAGE (IndexID=2): LIS PENDENS may appear here
- JUDGEMENT (IndexID=4): Foreclosure judgments
- TAXLIEN (IndexID=5): Tax lien filings

Built 2026-11-11 based on live reconnaissance of williamsburgsc instance.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# County configurations
COUNTIES = {
    "williamsburg": {"name": "Williamsburg", "row_estimate": 5800},
    "kershaw": {"name": "Kershaw", "row_estimate": 5800},
    "newberry": {"name": "Newberry", "row_estimate": 5744},
}

# Distress-related index IDs from live platform data
DISTRESS_INDICES = {
    1: "DEED",         # Deeds (includes foreclosure deeds, sheriff deeds)
    2: "MORTGAGE",     # Mortgages (includes LIS PENDENS sometimes)
    4: "JUDGEMENT",    # Judgments (foreclosure judgments)
    5: "TAXLIEN",      # Tax liens
}

# Lookback window (days) - conservative to get recent distress activity
_LOOKBACK_DAYS = int(os.environ.get("AVENU_LOOKBACK_DAYS", "90"))

# Instrument types that indicate foreclosure/distress
DISTRESS_KINDS = {
    "LIS PENDENS", "FC", "FORECLOSURE", "SHERIFF", "TAX",
    "JUDGMENT", "DECREE", "NOTICE OF SALE", "MASTER IN EQUITY"
}


def _parse_avenu_date(date_str: str | None) -> datetime | None:
    """Parse Avenu's /Date(milliseconds)/ format or MM/DD/YYYY string."""
    if not date_str:
        return None
    
    # Try /Date(...)/ format first
    m = re.search(r'/Date\((\d+)\)/', date_str)
    if m:
        ms = int(m.group(1))
        return datetime.utcfromtimestamp(ms / 1000.0)
    
    # Try MM/DD/YYYY format
    try:
        return datetime.strptime(date_str, "%m/%d/%Y")
    except:
        pass
    
    return None


def _is_distress_instrument(kind: str | None, description: str | None) -> bool:
    """Check if instrument type/description indicates distress."""
    if not kind and not description:
        return False
    
    text = f"{kind or ''} {description or ''}".upper()
    return any(kw in text for kw in DISTRESS_KINDS)


def _classify_listing(kind: str | None, description: str | None) -> ListingType:
    """Classify listing type based on instrument kind and description."""
    if not kind and not description:
        return ListingType.UNKNOWN
    
    text = f"{kind or ''} {description or ''}".upper()
    
    if "LIS PENDENS" in text or "NOTICE" in text:
        return ListingType.LIS_PENDENS
    if "FORECLOSURE" in text or "FC " in text:
        return ListingType.FORECLOSURE_SALE
    if "SHERIFF" in text or "MASTER IN EQUITY" in text or "AUCTION" in text:
        return ListingType.SHERIFF_SALE
    if "TAX" in text and "LIEN" in text:
        return ListingType.TAX_LIEN
    if "TAX" in text and "SALE" in text:
        return ListingType.TAX_SALE
    
    return ListingType.UNKNOWN


async def _login(c: httpx.AsyncClient, county: str) -> str:
    """Login to Avenu Insights for a county. Returns base URL."""
    base_url = f"https://{county}sc.avenuinsights.com"
    login_url = f"{base_url}/Public/{county}sc/Account/Login"
    
    # Get login page for CSRF token
    resp = await c.get(login_url)
    if resp.status_code != 200:
        raise RuntimeError(f"Login page failed: {resp.status_code}")
    
    # Extract __RequestVerificationToken
    token_match = re.search(
        r'name="__RequestVerificationToken"[^>]+value="([^"]+)"',
        resp.text
    )
    if not token_match:
        raise RuntimeError("No CSRF token found in login page")
    
    csrf_token = token_match.group(1)
    
    # Read credentials
    home = os.path.expanduser("~")
    email_path = os.path.join(home, ".secrets/avenu_insights/email.txt")
    password_path = os.path.join(home, ".secrets/avenu_insights/password.txt")
    
    with open(email_path) as f:
        email = f.read().strip()
    with open(password_path) as f:
        password = f.read().strip()
    
    # POST login
    login_data = {
        "__RequestVerificationToken": csrf_token,
        "Email": email,
        "Password": password,
    }
    
    resp2 = await c.post(login_url, data=login_data)
    if resp2.status_code != 200:
        raise RuntimeError(f"Login POST failed: {resp2.status_code}")
    
    # Check if login succeeded (should redirect to InstrumentGrid or contain "Logout")
    if "InstrumentGrid" not in str(resp2.url) and "Logout" not in resp2.text:
        raise RuntimeError("Login appears to have failed - no redirect or Logout link")
    
    log.info("avenu.login_success", county=county)
    return base_url


async def _search_instruments(
    c: httpx.AsyncClient, base_url: str, county: str, from_date: datetime, to_date: datetime
) -> list[dict]:
    """Search instruments via the platform's Search endpoint.
    
    This triggers a server-side search and stores results in session state.
    The grid then reads from that state. For now, we'll try the direct grid
    data endpoint if it exists, or parse the returned HTML.
    """
    search_url = f"{base_url}/Public/{county}sc/InstrumentGrid/Search"
    
    # Build search payload
    # Based on live testing, the platform accepts date range + index selections
    index_ids = ",".join(str(i) for i in DISTRESS_INDICES.keys())
    
    params = {
        "FromDate": from_date.strftime("%m/%d/%Y"),
        "ToDate": to_date.strftime("%m/%d/%Y"),
        "SelectedIndexIDs": index_ids,
        "SearchCriteria": "0",  # "All Records" search mode
        "take": 500,  # Max page size
        "skip": 0,
        "page": 1,
        "pageSize": 500,
    }
    
    resp = await c.post(search_url, data=params)
    if resp.status_code != 200:
        log.warning("avenu.search_failed", county=county, status=resp.status_code)
        return []
    
    # The search endpoint may return JSON status or HTML
    # Try JSON first
    try:
        data = resp.json()
        if data.get("status") == "Success":
            log.info("avenu.search_submitted", county=county)
            # Now we need to read the actual grid data
            # The grid's data endpoint is usually at InstrumentGrid/GridRead or similar
            # Let's try the standard Kendo Grid read pattern
            return await _read_grid_data(c, base_url, county)
        else:
            log.warning("avenu.search_status", county=county, status=data.get("status"))
            return []
    except:
        # Not JSON, might be HTML redirect
        log.info("avenu.search_response_html", county=county)
        return await _read_grid_data(c, base_url, county)


async def _read_grid_data(c: httpx.AsyncClient, base_url: str, county: str) -> list[dict]:
    """Read grid data after search is submitted.
    
    For Kendo Grid (which Avenu uses), data is typically at a Read endpoint.
    Since we don't have the exact endpoint from docs, we'll try common patterns.
    """
    # Try different possible grid read endpoints
    potential_endpoints = [
        f"{base_url}/Public/{county}sc/InstrumentGrid/GridRead",
        f"{base_url}/Public/{county}sc/InstrumentGrid/GetGridData",
        f"{base_url}/Public/{county}sc/InstrumentGrid/Read",
    ]
    
    for endpoint in potential_endpoints:
        try:
            resp = await c.post(endpoint, json={"take": 500, "skip": 0, "page": 1, "pageSize": 500})
            if resp.status_code == 200:
                data = resp.json()
                if "Data" in data and isinstance(data["Data"], list):
                    log.info("avenu.grid_data_found", county=county, endpoint=endpoint, records=len(data["Data"]))
                    return data["Data"]
        except Exception as e:
            log.debug("avenu.endpoint_failed", county=county, endpoint=endpoint, error=str(e)[:100])
            continue
    
    log.warning("avenu.no_grid_data", county=county)
    return []


def _build_listing(slug: str, county: str, base_url: str, record: dict) -> Listing | None:
    """Build a Listing from an Avenu Insights grid record."""
    # Extract fields
    instrument_id = record.get("InstrumentID")
    recorded_date_str = record.get("InstrumentDateAsString")
    direct_name = record.get("DirectName")  # Grantor
    indirect_name = record.get("IndirectName")  # Grantee
    instrument_num = record.get("Act")
    kind = record.get("Kind")  # Instrument type
    description = record.get("Description")
    book = record.get("Book")
    volume = record.get("Volume")
    page = record.get("Page")
    
    # Filter: only distress-related instruments
    if not _is_distress_instrument(kind, description):
        return None
    
    # Parse recorded date
    recorded_date = _parse_avenu_date(recorded_date_str)
    
    # Classify listing
    listing_type = _classify_listing(kind, description)
    
    # Build source URL (detail page)
    source_url = f"{base_url}/Public/{county}sc/InstrumentGrid/Details?InstrumentID={instrument_id}"
    
    # Determine owner/defendant name
    # For foreclosure-related documents, the grantee (indirect) is often the party in distress
    # For LIS PENDENS/notices, the defendant is usually the indirect name
    owner_name = indirect_name or direct_name
    
    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county=COUNTIES[county]["name"],
        case_number=instrument_num,
        defendant=owner_name,
        owner_name=owner_name,
        sale_date=recorded_date,  # Use sale_date field for recorded date
        description=description,
        legal_description=description,
        raw={
            "avenu_insights": {
                "county": county,
                "instrument_id": instrument_id,
                "instrument_number": instrument_num,
                "kind": kind,
                "description": description,
                "direct_name": direct_name,
                "indirect_name": indirect_name,
                "book": book,
                "volume": volume,
                "page": page,
                "recorded_date_string": recorded_date_str,
                "recorded_date": recorded_date.isoformat() if recorded_date else None,
            }
        },
    )


class ScAvenuRod(BaseScraper):
    slug = "counties_sc.sc_avenu_rod"
    name = "SC Avenu Insights ROD (Williamsburg, Kershaw, Newberry)"
    category = "county_rod"
    timeout_s = 480.0
    expected_min_count = 50  # Across all 3 counties

    async def fetch(self) -> Iterable[Listing]:
        out = self.partial
        to_date = datetime.utcnow()
        from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
        
        async with client(timeout=60.0) as c:
            for county_slug, county_info in COUNTIES.items():
                try:
                    log.info("avenu.county_start", county=county_slug)
                    
                    # Login
                    base_url = await _login(c, county_slug)
                    
                    # Search instruments
                    records = await _search_instruments(c, base_url, county_slug, from_date, to_date)
                    
                    # Build listings
                    county_count = 0
                    for record in records:
                        listing = _build_listing(self.slug, county_slug, base_url, record)
                        if listing:
                            out.append(listing)
                            county_count += 1
                    
                    log.info("avenu.county_done", county=county_slug, found=county_count)
                
                except Exception as exc:
                    log.error("avenu.county_error", county=county_slug, error=str(exc)[:200])
                    continue
        
        log.info("avenu.complete", total=len(out))
        return list(out)
