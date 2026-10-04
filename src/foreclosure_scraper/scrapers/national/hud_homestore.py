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

The searchresult JSON used to show only the first ~9 listings per the
original 2026-06 build notes; live-reverified 2026-10-04 (national.*
extraction-completeness audit, batch 16) and the handler now returns the
FULL state result set directly in `searchresult` (17 NC / 10 SC today,
cross-checked 1:1 against MapModel.ListingsPins' case-number set, which
carries no case this one doesn't already have) -- no pagination or
pins-join is actually needed any more.

Free, no Apify dependency, no headless browser required.

FIXED 2026-10-04 (same audit): confirmed via a direct `_slim_raw()`
round-trip that 9 of this scraper's 11 raw keys (`fha_financing`,
`listing_period`, `property_status`, `bid_open_date`,
`period_deadline_date`, `bedrooms`, `bathrooms`, `sqft`, `year_built`) were
never registered in `web_artifact.RAW_KEEP` as flat top-level keys and have
been silently dropped at every publish since this scraper was built --
exactly the failure mode this project's extraction-gaps audit keeps
finding (see batch 7's `anderson_mie_deficiency` / batch 15's `documents`).
Fixed two ways: (1) `bedrooms`/`bathrooms`/`sqft`->`living_sqft`/
`year_built` are promoted to the Listing's own first-class fields (which
always serialize, no RAW_KEEP entry needed at all -- the more correct fix,
matching how sibling REO scrapers freddie_homesteps/hubzu already do it);
(2) the remaining HUD-specific metadata moves into a nested
`raw["hud_homestore"]` dict, registered `"hud_homestore": "*"` in
RAW_KEEP. Also added: each listing's own `/propertydetails?caseNumber=`
page (confirmed live, NO auth/token needed, unlike the search handler)
carries a "Listing Broker" contact block with a real name + direct phone +
email (live example: "COREY ADAMSKI", "(828) 231-4430",
"COREYADAMSKI@GMAIL.COM") -- genuine free contactability HERMES sec 9
calls the #1 ceiling, previously never fetched at all. Also captured from
that same searchresult row (also previously dropped): `inAmenities`/
`outAmenities`/`parkingType`/`numberOfStories` and `bidderTypes`/
`eligibleBidders` (who may currently bid -- e.g. "Owner Occupant" vs
"All Bidders" periods).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

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


def _extract_broker(html: str) -> dict:
    """The per-case `/propertydetails` page's "Listing Broker" card: a real
    name, direct phone (plain `tel:` href, not obfuscated), and email (the
    Cloudflare-obfuscated `__cf_email__` span's PLAIN-TEXT value is already
    sitting in the same `<a>`'s `title` attribute -- no hex decode needed).
    Scoped to the "Listing Broker" h2's own card so it can't pick up the
    page's separate "Asset Manager" or "Field Service Manager" contacts,
    which use the identical markup shape."""
    if not html:
        return {}
    tree = HTMLParser(html)
    for h2 in tree.css("h2"):
        if h2.text(strip=True) != "Listing Broker":
            continue
        container = h2.parent
        depth = 0
        while container is not None and depth < 6:
            cls = container.attributes.get("class") or ""
            if "row" in cls.split():
                break
            container = container.parent
            depth += 1
        if container is None:
            break
        out: dict = {}
        name_el = container.css_first("div.font-weight-bold")
        if name_el is not None:
            out["name"] = name_el.text(strip=True) or None
        tel = container.css_first('a[href^="tel:"]')
        if tel is not None:
            # Read the href, not the link text: the <a> wraps BOTH a
            # visually-hidden "Listing Broker's Phone number" <span
            # class=sr-only> AND the visible number in a sibling <span> --
            # .text() concatenates both ("Listing Broker's Phone
            # number(828) 231-4430", confirmed live) with no separator.
            href = (tel.attributes.get("href") or "")
            out["phone"] = href[4:].strip() or None if href.startswith("tel:") else None
        for a in container.css("a[title]"):
            title = (a.attributes.get("title") or "").strip()
            if "@" in title:
                out["email"] = title
                break
        return {k: v for k, v in out.items() if v}
    return {}


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

    # HUD encodes images two ways:
    #   propertyThumb = single Cloudinary CDN URL
    #   galleryImages = quoted-comma-joined filenames; not full URLs but the
    #                   propertyThumb URL prefix is consistent and can be
    #                   reused to build the full URLs.
    photos: list[str] = []
    thumb = p.get("propertyThumb")
    if isinstance(thumb, str) and thumb.startswith("http"):
        photos.append(thumb)
    gallery = p.get("galleryImages") or ""
    if isinstance(gallery, str) and gallery and thumb and "/hhs/" in thumb:
        prefix = thumb.rsplit("/", 1)[0] + "/"
        for fn in re.findall(r'"([^"]+\.(?:jpg|jpeg|png))"', gallery):
            full = prefix + fn
            if full not in photos:
                photos.append(full)
        photos = photos[:6]

    return Listing(
        source="national.hud_homestore",
        # 2026-10-04: /propertydetails?caseNumber=<case> is a REAL, stable,
        # auth-free per-property deep link (live-confirmed across multiple
        # cases) -- the 2026-06-19 note that HUD has no stable public
        # detail link was about a DIFFERENT, wrong path
        # (/Listing/PropertyDetails, capital-L, which does 404). Falls back
        # to the state search page only if a row somehow has no case number.
        source_url=(f"{BASE}/propertydetails?caseNumber={case}" if case
                    else f"{BASE}/searchresult?stateCode={state}"),
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
        # Promoted to first-class fields 2026-10-04 (were raw-only flat
        # scalar keys -- "bedrooms"/"bathrooms"/"sqft"/"year_built" --
        # never registered in web_artifact.RAW_KEEP, so silently dropped at
        # every publish; a first-class Listing field always serializes and
        # sidesteps that allowlist entirely, same pattern freddie_homesteps/
        # hubzu already use).
        bedrooms=_safe_int(p.get("bedrooms")),
        bathrooms=_safe_float(p.get("bathrooms")),
        living_sqft=_safe_float(p.get("squareFootage")),
        year_built=_safe_int(p.get("yearBuilt")),
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
            "images": {"real": photos} if photos else {},
            # Nested 2026-10-04 under a RAW_KEEP-registered ("*") key --
            # these used to be flat top-level scalars with no registration
            # at all (see module docstring).
            "hud_homestore": {
                "fha_financing": p.get("fhaFinancing"),
                "listing_period": p.get("listingPeriod"),
                "property_status": p.get("propertyStatus"),
                "bid_open_date": p.get("bidOpenDate"),
                "period_deadline_date": p.get("periodDeadlineDate"),
                # Real structured features stated on the card but never
                # captured at all before this audit.
                "in_amenities": (p.get("inAmenities") or "").strip() or None,
                "out_amenities": (p.get("outAmenities") or "").strip() or None,
                "parking_type": (p.get("parkingType") or "").strip() or None,
                "number_of_stories": _safe_float(p.get("numberOfStories")),
                "bidder_types": (p.get("bidderTypes") or "").strip() or None,
                "eligible_bidders": (p.get("eligibleBidders") or "").strip() or None,
            },
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

        # Step 3: per-listing Listing Broker contact (name/phone/email) --
        # a real, auth-free per-case detail page (see module docstring),
        # fetched on the SAME client so the connection is reused. One extra
        # request per listing; the state's whole result set is small
        # (17 NC / 10 SC live 2026-10-04), so this stays cheap.
        for li in out:
            if not li.case_number:
                continue
            try:
                dr = await c.get(
                    f"{BASE}/propertydetails?caseNumber={li.case_number}",
                    headers=HEADERS, follow_redirects=True,
                )
            except Exception as exc:
                log.warning("hud.broker_fetch_failed", case=li.case_number,
                            error=str(exc)[:160])
                continue
            if dr.status_code != 200:
                continue
            broker = _extract_broker(dr.text)
            if broker:
                li.raw.setdefault("hud_homestore", {})["listing_broker"] = broker

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
