"""GSA federal surplus real property — realestatesales.gov.

The U.S. General Services Administration auctions surplus FEDERAL real property
(former reserve centers, post offices, residences, land) at realestatesales.gov.
These are genuine REO / government-disposal leads: GSA holds clean federal title
and is a motivated institutional seller. National volume is small and sporadic
(~12 active listings nationwide at any time), so in-footprint (W-NC + Upstate-SC)
hits are rare — but each one is high value, so we keep the watcher running with
expected_min_count=0.

Access path (free, public, server-rendered HTML — NO login, NO CAPTCHA):
  1. GET /our-listing/  -> the full active-inventory index page. Server-rendered;
     every property card carries an `/asset-details/?property_id=N` link. (The
     site's /api/properties JSON is login-walled, so we scrape the rendered
     index instead — explicitly NOT the API.)
  2. GET /asset-details/?property_id=N for each id -> the detail page. Fields are
     parsed from the page, NOT the API:
       - twitter:title / og:title meta = "<street> <City>, <ST>, <ZIP>"
         (verified the cleanest single source of the full mailing line).
       - "Starting Bid: $N" -> opening_bid.
       - "Property Type: <X>"  -> property_kind mapping.
       - "Asset Type: <Commercial|Residential|Land>" -> kind fallback + label.
       - "Case Number: <X>" / "Sale Number: <X>".
       - "Online Auction" / "Sealed Bid" banner -> auction style.
       - inspection / bid-close dates live in the IFB PDF, not the page, so
         sale_date is best-effort (often None) — left null rather than guessed.
  3. Filter to NC/SC by the parsed state, then map the city to a county via the
     in-footprint city tables so out-of-core rows (e.g. coastal-only) can still
     be flagged downstream. Only NC/SC rows are emitted.

Verified live 2026-06-30: 12 active listings (MI, VT, NJ, TX×7, IN, UT); parser
extracts address/city/state/zip/type/bid for each. No NC/SC currently active, so
a clean 0 is the expected off-footprint outcome (ZERO_RESULT, not an error).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...http_client import get_text
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://realestatesales.gov"
_INDEX = f"{_BASE}/our-listing/"

# Only emit rows in our core states. (City->county is best-effort below.)
_CORE_STATES = {"NC", "SC"}

# Property Type / Asset Type text -> PropertyKind.
_KIND_MAP = {
    "residential": PropertyKind.SINGLE_FAMILY,
    "single family": PropertyKind.SINGLE_FAMILY,
    "single-family": PropertyKind.SINGLE_FAMILY,
    "multi family": PropertyKind.MULTI_FAMILY,
    "multi-family": PropertyKind.MULTI_FAMILY,
    "commercial": PropertyKind.COMMERCIAL,
    "industrial": PropertyKind.COMMERCIAL,
    "office": PropertyKind.COMMERCIAL,
    "mixed use": PropertyKind.MIXED,
    "mixed-use": PropertyKind.MIXED,
    "land": PropertyKind.LAND,
    "vacant land": PropertyKind.LAND,
}

_ID_RE = re.compile(r"asset-details/?\?property_id=(\d+)", re.I)
# "<street> <City>, <ST>, <ZIP>" — split on the LAST two commas.
_LOC_RE = re.compile(r"^(.*?),\s*([A-Za-z]{2}),\s*(\d{5})(?:-\d{4})?\s*$")
_BID_RE = re.compile(r"Starting Bid:.*?\$\s*([\d,]+(?:\.\d{2})?)", re.I | re.S)
_PTYPE_RE = re.compile(r"Property Type:\s*</strong>\s*([A-Za-z /&-]+?)\s*</li>", re.I)
_ATYPE_RE = re.compile(r"Asset Type:\s*</strong>\s*([A-Za-z /&-]+?)\s*</li>", re.I)
_CASE_RE = re.compile(r"Case Number:\s*(?:</[^>]+>\s*)?([A-Z0-9-]+)", re.I)
_SALE_RE = re.compile(r"Sale Number:\s*(?:</[^>]+>\s*)?([A-Z0-9-]+)", re.I)
_SQFT_RE = re.compile(r"Square Footage:\s*</strong>\s*([\d,]+)", re.I)
_YEAR_RE = re.compile(r"Year Built:\s*</strong>\s*(\d{4})", re.I)
_ACRE_RE = re.compile(r"Lot Size:\s*</strong>\s*([\d.]+)\s*Acres", re.I)


def _meta(html: str, key: str) -> str | None:
    """Return a twitter:/og: meta content value, or None."""
    m = re.search(
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']*)',
        html, re.I,
    )
    if m:
        return m.group(1).strip() or None
    # Some templates put content before name/property — try the reverse order.
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']{re.escape(key)}["\']',
        html, re.I,
    )
    return (m.group(1).strip() or None) if m else None


def _float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _county_for(city: str | None, state: str) -> str | None:
    """Best-effort city -> in-footprint county. Returns None when unknown
    (the row is still emitted; downstream GIS/owner enrichers can backfill)."""
    if not city:
        return None
    try:
        from ..._upstate_city_to_county import upstate_county_for
        return upstate_county_for(city, state)
    except Exception:  # noqa: BLE001
        return None


def parse_detail(html: str, pid: str, url: str) -> Listing | None:
    """Parse one asset-detail page into a Listing, or None if not NC/SC / no addr."""
    title = _meta(html, "twitter:title") or _meta(html, "og:title")
    if not title:
        return None
    m = _LOC_RE.match(re.sub(r"\s+", " ", title).strip())
    if not m:
        return None
    street, state, zip_code = m.group(1).strip(), m.group(2).upper(), m.group(3)
    if state not in _CORE_STATES:
        return None

    # street cell often ends with the city (no comma): "<street...> <City>".
    # The mailing line is "<street> <City>, ST, ZIP" so everything before the
    # first comma is "street + city". We can't reliably split street from city
    # without a delimiter, so keep the whole pre-comma chunk as street_address
    # and pull city from the IFB block when present; else leave city None.
    city = None
    # Property Highlights sometimes lists "City: X" — opportunistic.
    cm = re.search(r"City:\s*</strong>\s*([A-Za-z .'-]+?)\s*</li>", html, re.I)
    if cm:
        city = cm.group(1).strip()

    ptype = (_PTYPE_RE.search(html) or [None, None])
    ptype_val = ptype.group(1).strip().lower() if ptype else None
    atype = _ATYPE_RE.search(html)
    atype_val = atype.group(1).strip() if atype else None
    kind = (
        _KIND_MAP.get(ptype_val or "")
        or _KIND_MAP.get((atype_val or "").lower())
        or PropertyKind.UNKNOWN
    )

    bid = None
    bm = _BID_RE.search(html)
    if bm:
        bid = _float(bm.group(1))

    case = (_CASE_RE.search(html).group(1) if _CASE_RE.search(html) else None)
    sale_no = (_SALE_RE.search(html).group(1) if _SALE_RE.search(html) else None)
    sqft = _float(_SQFT_RE.search(html).group(1)) if _SQFT_RE.search(html) else None
    year = int(_YEAR_RE.search(html).group(1)) if _YEAR_RE.search(html) else None
    acres = _float(_ACRE_RE.search(html).group(1)) if _ACRE_RE.search(html) else None
    style = "Online Auction" if "Online Auction" in html else (
        "Sealed Bid" if "Sealed Bid" in html else "GSA Auction")

    county = _county_for(city, state)
    label = atype_val or (ptype_val.title() if ptype_val else "Real Property")

    return Listing(
        source="national.gsa_realproperty",
        source_url=url,
        listing_type=ListingType.REO,
        property_kind=kind,
        street_address=street or None,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        opening_bid=bid,
        living_sqft=sqft,
        year_built=year,
        acreage=acres,
        case_number=case,
        plaintiff="U.S. General Services Administration",
        description=(f"GSA federal surplus {label} ({style}) — {state}").strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"gsa": {
            "property_id": pid,
            "sale_number": sale_no,
            "asset_type": atype_val,
            "property_type": ptype_val,
            "auction_style": style,
        }},
    )


class GSARealProperty(BaseScraper):
    slug = "national.gsa_realproperty"
    name = "GSA Federal Surplus Real Property (realestatesales.gov)"
    category = "federal_reo"
    timeout_s = 180.0
    expected_min_count = 0  # National inventory is tiny; NC/SC hits are sporadic.
    requires_apify = False

    async def fetch(self) -> Iterable[Listing]:
        try:
            index_html = await get_text(_INDEX, impersonate=True, timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("gsa.index_fail", error=str(exc)[:200])
            return []

        ids = sorted({m.group(1) for m in _ID_RE.finditer(index_html)}, key=int)
        log.info("gsa.index_ok", ids=len(ids))
        out: list[Listing] = []
        for pid in ids:
            url = f"{_BASE}/asset-details/?property_id={pid}"
            try:
                html = await get_text(url, impersonate=True, timeout=60.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("gsa.detail_fail", pid=pid, error=str(exc)[:160])
                continue
            try:
                li = parse_detail(html, pid, url)
            except Exception as exc:  # noqa: BLE001
                log.warning("gsa.parse_fail", pid=pid, error=str(exc)[:160])
                continue
            if li is not None:
                out.append(li)
                log.info("gsa.hit", pid=pid, state=li.state, city=li.city)
        log.info("gsa.done", count=len(out), scanned=len(ids))
        return out
