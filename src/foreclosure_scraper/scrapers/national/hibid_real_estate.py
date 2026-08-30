"""HiBid — national auction aggregator, NC/SC real-estate lots (free JSON API).

HiBid is an Angular PWA fronting an Apollo **GraphQL** endpoint at
``https://hibid.com/graphql`` (discovered in the PWA bundle: the app builds
``apiBaseUrl.replace("{hostname}", location.hostname) + "/graphql"``). We hit
that endpoint directly — far more reliable than rendering the SPA — with the
``lotSearch`` operation, scoped to the global **Real Estate** category
(``40060``) and a US state (the input's ``state`` field). This is the catch-all
net: small NC/SC auctioneers list estate / distressed / land / tax real estate
here.

Why it stays accurate over high-volume:
  * ``category: 40060`` + ``state`` already excludes the equipment/collectible
    firehose — every row is in the Real Estate category for that state.
  * We still REQUIRE a parseable street address out of the lot ``lead`` (title)
    or ``description`` and SKIP anything address-less, so a generically-titled
    lot ("Premium Brick Ranch") is dropped rather than emitted as junk.

Field notes (verified 2026-08-17):
  * lot.lead = title (often carries the address, e.g. "887 Snug Harbor Rd
    Hertford, NC"); lot.description = long text (address + "Harnett County" +
    acreage often live here, e.g. "197 Smooth Rock Pt., Ridgeway, SC 29130").
  * auction.eventCity / eventState / eventZip = the auctioneer's event location;
    for these single-property real-estate auctions it is almost always the
    property's town, so we use it as a fallback city/zip and trust eventState
    (== the state we queried) for NC/SC.
  * auction.bidCloseDateTime / eventDateEnd = the auction end → sale_date.
  * lot.bidAmount comes back as a constant sentinel ``123.45`` to
    unauthenticated callers, so it is NOT a real price — ignored.

Free, no auth, no Apify.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

GRAPHQL_URL = "https://hibid.com/graphql"
REAL_ESTATE_CATEGORY = 40060  # global "Real Estate" CategoryId (both NC & SC pages use it)
STATES = ("NC", "SC")
PAGE_LENGTH = 100
PAGES_CAP = 10  # 100*10 = 1000 lots/state headroom; real-estate volumes are far lower
BOGUS_BID = 123.45  # sentinel HiBid returns for bidAmount to unauth callers

# We request only the subset of the schema we use (GraphQL allows field subsets).
_QUERY = """
query LotSearch($pageNumber: Int!, $pageLength: Int!, $category: CategoryId, $state: String) {
  lotSearch(
    input: {category: $category, state: $state, countAsView: false}
    pageNumber: $pageNumber
    pageLength: $pageLength
    sortDirection: DESC
  ) {
    pagedResults {
      totalCount
      results {
        id
        lead
        description
        bidAmount
        estimate
        category { id categoryName }
        auction {
          id
          eventName
          eventCity
          eventState
          eventZip
          eventAddress
          eventDateBegin
          eventDateEnd
          bidCloseDateTime
          auctioneer { name }
        }
      }
    }
  }
}
"""

_HEADERS = {
    "Origin": "https://hibid.com",
    "Referer": "https://hibid.com/",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Street-address matcher: <number> <1-4 words> <suffix>. Suffixes cover the
# common long + abbreviated forms seen in these listings (Rd/Road, Pt/Point ...).
_SUFFIX = (
    r"St|Street|Rd|Road|Dr|Drive|Ave|Avenue|Ln|Lane|Ct|Court|Pl|Place|"
    r"Blvd|Boulevard|Way|Cir|Circle|Hwy|Highway|Trl|Trail|Pkwy|Parkway|"
    r"Pike|Pt|Point|Loop|Run|Path|Row|Ter|Terrace|Cove|Cv|Landing|Xing|"
    r"Crossing|Ridge|Sq|Square|Bnd|Bend|Manor|Mnr|Walk|Grove|Gln|Glen|Knoll|Vw|View"
)
_ADDR_RE = re.compile(
    r"\b(\d{1,6}\s+(?:[A-Za-z0-9.'\-]+\s+){0,4}(?:" + _SUFFIX + r"))\.?\b",
)
# City, ST[ zip] trailing the street match.
_CITYSTZIP_RE = re.compile(
    r"[,\s]+([A-Za-z][A-Za-z .'\-]+?),?\s+(NC|SC)\b(?:\s+(\d{5}))?",
)
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_COUNTY_RE = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+County\b")

# Blacklist of false-positive "streets" — numeric qualifiers that end in a token
# that looks like a suffix but is really a spec ("2 Story", "1 Run" is fine; guard
# obvious specs). Kept minimal; the number+suffix shape already filters most.
_BAD_ADDR_TOKENS = ("sq ft", "square feet", "square foot")


def _parse_dt(*vals: str | None) -> datetime | None:
    for v in vals:
        if not v:
            continue
        s = str(v).strip().replace("Z", "")
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[: len(fmt) + 2] if "T" in s else s, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            continue
    return None


def _extract_address(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (street_address, city, zip) parsed from lot text, or (None,..)."""
    if not text:
        return None, None, None
    for m in _ADDR_RE.finditer(text):
        street = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
        low = street.lower()
        if any(b in low for b in _BAD_ADDR_TOKENS):
            continue
        # Need at least a street-name word between number and suffix, e.g.
        # "197 Pt" (2 tokens) is too thin; "12 Oak St" (3 tokens) is fine.
        if len(street.split()) < 3:
            continue
        tail = text[m.end(): m.end() + 60]
        city = zc = None
        cm = _CITYSTZIP_RE.match(tail) or _CITYSTZIP_RE.search(tail)
        if cm:
            city = cm.group(1).strip().title()
            zc = cm.group(3)
        if not zc:
            zm = _ZIP_RE.search(tail)
            if zm:
                zc = zm.group(1)
        return street, city, zc
    return None, None, None


def _property_kind(lead: str, desc: str, cat_name: str | None) -> PropertyKind:
    blob = f"{lead} {desc} {cat_name or ''}".lower()
    if any(w in blob for w in ("commercial", "retail", "office", "warehouse", "industrial")):
        return PropertyKind.COMMERCIAL
    if any(w in blob for w in ("acre", "lot", "tract", "parcel", "land", "acreage")):
        # but a "3 lot" of a house? prefer LAND only when no dwelling word present
        if not any(w in blob for w in ("home", "house", "ranch", "bedroom", "bath", "residence", "condo")):
            return PropertyKind.LAND
    if "condo" in blob:
        return PropertyKind.CONDO
    if any(w in blob for w in ("townhouse", "townhome")):
        return PropertyKind.TOWNHOUSE
    if any(w in blob for w in ("duplex", "multi-family", "multifamily", "triplex", "fourplex")):
        return PropertyKind.MULTI_FAMILY
    if "mobile" in blob or "manufactured" in blob:
        return PropertyKind.MOBILE
    if any(w in blob for w in ("home", "house", "ranch", "bedroom", "bath", "residence", "cottage")):
        return PropertyKind.SINGLE_FAMILY
    return PropertyKind.UNKNOWN


async def _post(payload: dict) -> dict | None:
    """POST the GraphQL query via the shared throttled httpx client, falling back
    to a curl-cffi Chrome fingerprint if the plain client is fingerprint-blocked."""
    from ...http_client import client

    try:
        async with client(timeout=45.0, headers=_HEADERS) as c:
            r = await c.post(GRAPHQL_URL, json=payload)
            if r.status_code == 200:
                return r.json()
            log.warning("hibid.http_status", code=r.status_code)
    except Exception as exc:  # noqa: BLE001
        log.warning("hibid.httpx_fail", error=str(exc)[:160])

    # Fallback: curl-cffi impersonation (same tier http_client uses for GETs).
    try:
        from curl_cffi.requests import AsyncSession

        async with AsyncSession() as s:
            r = await s.post(GRAPHQL_URL, json=payload, impersonate="chrome",
                             headers=_HEADERS, timeout=45)
            if r.status_code == 200:
                return r.json()
            log.warning("hibid.impersonate_status", code=r.status_code)
    except Exception as exc:  # noqa: BLE001
        log.warning("hibid.impersonate_fail", error=str(exc)[:160])
    return None


async def _fetch_state(state: str) -> list[Listing]:
    out: list[Listing] = []
    seen: set[int] = set()
    for page in range(1, PAGES_CAP + 1):
        payload = {
            "operationName": "LotSearch",
            "query": _QUERY,
            "variables": {
                "pageNumber": page,
                "pageLength": PAGE_LENGTH,
                "category": REAL_ESTATE_CATEGORY,
                "state": state,
            },
        }
        data = await _post(payload)
        if not data:
            break
        paged = (((data or {}).get("data") or {}).get("lotSearch") or {}).get("pagedResults") or {}
        results = paged.get("results") or []
        total = paged.get("totalCount") or 0
        if not results:
            break

        for lot in results:
            try:
                li = _build_listing(state, lot)
            except Exception as exc:  # noqa: BLE001 - one bad lot must not kill the page
                log.warning("hibid.lot_parse_fail", error=str(exc)[:140])
                continue
            if li is not None:
                out.append(li)

        seen.update(l.get("id") for l in results if l.get("id"))
        log.info("hibid.page", state=state, page=page, got=len(results),
                 kept=len(out), total=total)
        if len(seen) >= total or len(results) < PAGE_LENGTH:
            break
    return out


def _build_listing(state: str, lot: dict) -> Listing | None:
    lead = (lot.get("lead") or "").strip()
    desc = (lot.get("description") or "").strip()
    auction = lot.get("auction") or {}
    lot_id = lot.get("id")
    if not lot_id:
        return None

    # Require a resolvable street address from title or description.
    street, city, zc = _extract_address(lead)
    if not street:
        street, city, zc = _extract_address(desc)
    if not street:
        return None  # accuracy over volume — skip address-less lots

    # Fill gaps from the auction event location (property town for these sales).
    city = city or (auction.get("eventCity") or None)
    zc = zc or (auction.get("eventZip") or None)
    ev_state = (auction.get("eventState") or state or "").upper() or None

    county = None
    cm = _COUNTY_RE.search(desc) or _COUNTY_RE.search(lead)
    if cm:
        county = cm.group(1).strip()

    cat_name = None
    for c in (lot.get("category") or []):
        n = (c or {}).get("categoryName")
        if n and n.lower() != "real estate":
            cat_name = n
            break

    sale_date = _parse_dt(auction.get("bidCloseDateTime"),
                          auction.get("eventDateEnd"),
                          auction.get("eventDateBegin"))

    bid = lot.get("bidAmount")
    opening_bid = None
    try:
        if bid is not None and float(bid) not in (0.0, BOGUS_BID):
            opening_bid = float(bid)
    except (TypeError, ValueError):
        pass

    source_url = f"https://hibid.com/lot/{lot_id}"

    return Listing(
        source="national.hibid_real_estate",
        source_url=source_url,
        listing_type=ListingType.AUCTION,
        property_kind=_property_kind(lead, desc, cat_name),
        street_address=street,
        city=city,
        state=ev_state or state,
        zip_code=(zc[:5] if zc else None),
        county=county,
        sale_date=sale_date,
        opening_bid=opening_bid,
        description=(f"HiBid auction — {lead}" if lead else "HiBid real-estate auction")[:300],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"hibid": {
            "lot_id": lot_id,
            "auction_id": auction.get("id"),
            "auctioneer": (auction.get("auctioneer") or {}).get("name"),
            "event_name": auction.get("eventName"),
            "event_city": auction.get("eventCity"),
            "event_state": auction.get("eventState"),
            "event_address": auction.get("eventAddress"),
            "sub_category": cat_name,
            "lead": lead[:200] or None,
        }},
    )


class HibidRealEstate(BaseScraper):
    slug = "national.hibid_real_estate"
    name = "HiBid Real Estate (NC/SC)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in STATES:
            try:
                rows = await _fetch_state(state)
                out.extend(rows)
                log.info("hibid.state_done", state=state, count=len(rows))
            except Exception as exc:  # noqa: BLE001
                log.warning("hibid.state_failed", state=state, error=str(exc)[:200])
        return out
