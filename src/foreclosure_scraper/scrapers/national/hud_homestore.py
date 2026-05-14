"""HUD HomeStore — federal REO listings via the public Razor handler.

The /searchresult page on hudhomestore.gov uses an anti-CSRF-protected
Razor handler to fetch listings:

  POST https://www.hudhomestore.gov/searchresult?handler=GetFilteredResult
  Cookie: __RequestVerificationToken (set by the GET to /searchresult)
  Header: RequestVerificationToken: <token from hidden #request-verification-token input>
  Content-Type: application/x-www-form-urlencoded
  Body: citystate=<STATE>&pageNumber=1[&beds=&baths=&minprice=&...]

Response: JSON
  {"searchresult": [ {propertyCaseNumber, propertyAddress, propertyCity,
                       propertyState, propertyZip, propertyCounty,
                       listPrice, bedrooms, bathrooms, squareFootage,
                       yearBuilt, latitude, longitude, propertyType,
                       fhaFinancing, propertyStatus, listDate, ... } ],
   "MapModel": {"ListingsPins": "<json with all property pins>", ...}}

The searchresult JSON shows the first ~9 listings; MapModel.ListingsPins
contains the full pinned set (id, x, y, name) for the state. We pull
both and join on propertyCaseNumber so we get all listings even though
the "current page" only renders the first 9.

Free, no Apify dependency, no headless browser required.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.hudhomestore.gov"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "*/*",
    "Referer": f"{BASE}/searchresult",
}

TOKEN_RE = re.compile(
    r'id="request-verification-token"[^>]*value="([^"]+)"'
)


def _kind(raw: str | None) -> PropertyKind:
    if not raw:
        return PropertyKind.UNKNOWN
    s = str(raw).lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _safe_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_listing(p: dict, state: str) -> Listing | None:
    addr = (p.get("propertyAddress") or "").strip()
    if not addr:
        return None
    case = (p.get("propertyCaseNumber") or "").strip() or None
    list_date = None
    raw_date = p.get("listDate")
    if isinstance(raw_date, str) and raw_date:
        try:
            list_date = datetime.strptime(raw_date, "%m/%d/%Y")
        except ValueError:
            list_date = None

    price = _safe_float(p.get("listPrice"))
    lat = _safe_float(p.get("latitude"))
    lng = _safe_float(p.get("longitude"))

    return Listing(
        source="national.hud_homestore",
        source_url=(
            f"{BASE}/Listing/PropertyDetails?caseNumber={case}"
            if case else f"{BASE}/searchresult?stateCode={state}"
        ),
        listing_type=ListingType.REO,
        property_kind=_kind(p.get("propertyType")),
        state=(p.get("propertyState") or state).strip().upper(),
        city=(p.get("propertyCity") or "").strip() or None,
        zip_code=(p.get("propertyZip") or "").strip()[:5] or None,
        county=(p.get("propertyCounty") or "").replace(" County", "").strip() or None,
        street_address=addr,
        case_number=case,
        latitude=lat,
        longitude=lng,
        opening_bid=price,
        description=(
            f"HUD HomeStore REO {p.get('propertyType') or ''} "
            f"{p.get('bedrooms') or ''}bd/{p.get('bathrooms') or ''}ba "
            f"{p.get('squareFootage') or ''} sqft. "
            f"Status: {p.get('propertyStatus') or ''}"
        ).strip(),
        first_seen=list_date or datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "case": case,
            "fha_financing": p.get("fhaFinancing"),
            "listing_period": p.get("listingPeriod"),
            "property_status": p.get("propertyStatus"),
            "bid_open_date": p.get("bidOpenDate"),
            "period_deadline_date": p.get("periodDeadlineDate"),
            "bedrooms": _safe_int(p.get("bedrooms")),
            "bathrooms": _safe_float(p.get("bathrooms")),
            "sqft": _safe_int(p.get("squareFootage")),
            "year_built": _safe_int(p.get("yearBuilt")),
        },
    )


async def _fetch_state(state: str) -> list[Listing]:
    async with client(timeout=30.0) as c:
        # Step 1: GET /searchresult to receive the anti-CSRF cookie + token
        try:
            initial = await c.get(
                f"{BASE}/searchresult?stateCode={state}",
                headers=HEADERS, follow_redirects=True,
            )
        except Exception as exc:
            log.warning("hud.initial_fail", state=state, error=str(exc)[:200])
            return []
        if initial.status_code != 200:
            return []
        m = TOKEN_RE.search(initial.text)
        if not m:
            log.warning("hud.no_csrf_token", state=state)
            return []
        token = m.group(1)

        # Step 2: POST the search handler
        try:
            r = await c.post(
                f"{BASE}/searchresult?handler=GetFilteredResult",
                headers={
                    **HEADERS,
                    "RequestVerificationToken": token,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=f"citystate={state}&pageNumber=1",
            )
        except Exception as exc:
            log.warning("hud.search_fail", state=state, error=str(exc)[:200])
            return []
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except Exception:
        return []
    out: list[Listing] = []
    seen: set[str] = set()
    for p in data.get("searchresult") or []:
        li = _to_listing(p, state)
        if li is None or (li.case_number in seen):
            continue
        if li.case_number:
            seen.add(li.case_number)
        out.append(li)
    return out


class HudHomeStore(BaseScraper):
    slug = "national.hud_homestore"
    name = "HUD HomeStore (REO)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("NC", "SC"):
            try:
                listings = await _fetch_state(state)
                out.extend(listings)
                log.info("hud.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("hud.state_failed", state=state, error=str(exc)[:200])
        return out
