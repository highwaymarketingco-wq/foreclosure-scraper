"""US Marshals Service real-property forfeiture sales — via RealLook.com.

REWRITTEN 2026-10-01 (national-auction-tier audit, batch 4). The old target
URL (usmarshals.gov/what-we-do/asset-forfeiture/real-property/) is a hard
404 today. Checked usmarshals.gov's current Asset Forfeiture page and found
the agency no longer lists real property on its own site at all: "the
properties sold by the U.S. Marshals Service are sold by utilizing
traditional means of listing the properties with a licensed broker ... as
well as RealLook.com which is the website run by the U.S. Marshals
Service's Real Property National Contractor (RPNC)." So RealLook.com IS
the new, correct, free, public, no-login target.

The old scraper's own extraction approach is also the exact
"fabricated-row" shape this project has been bitten by before: it scanned
raw body TEXT for a generic street/city/state/zip regex across the whole
page with no connection to a real listing boundary, which is how an
unrelated address mentioned anywhere on the page (nav, footer, an
unrelated example) could become a fake Listing. Replaced entirely with a
structured parse of RealLook's own per-property cards and detail pages.

Access path (free, public, server-rendered, no login, no CAPTCHA):
  1. GET https://reallook.com/properties?page=N -- plain server-rendered
     HTML, ~12 cards/page (confirmed live: 88 total properties nationwide
     across 8 pages). Each card's own text already carries the full
     address line ("<street>, <city>, <ST> <zip>"), so we filter to NC/SC
     at this cheap list-page step before ever fetching a detail page.
  2. GET https://reallook.com/properties/{id}-0 for each NC/SC hit (never
     for out-of-state cards, so this stays cheap even though the detail
     page carries much richer data): price, sqft, acreage, Property Type,
     Status (drop "Under Contract"/"Sold"/"Off Market" -- not actionable,
     same posture as national.gsa_surplus's closed-tag filter), Year
     Built, COUNTY (given directly, no gazetteer guess needed), broker
     name/phone, real listing photos
     (storage/properties/{id}/images/mkt_*.jpg), and real documents
     (storage/properties/{id}/files/*.pdf, e.g. a brochure) -- wired via
     harvest_document_links()/stamp_documents().

Free, no login, no CAPTCHA, no Akamai/WAF challenge encountered.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://reallook.com"
_LIST_URL = f"{_BASE}/properties"
_CORE_STATES = {"NC", "SC"}
_PAGES_CAP = 30  # current inventory is 88/~12 per page = 8 pages; headroom for growth

# Statuses that mean the property is no longer actionable -- same posture as
# national.gsa_surplus's _CLOSED_TAGS (sold/disposed/under-contract rows are
# dropped, not just flagged).
_CLOSED_STATUSES = {"sold", "under contract", "off market", "pending", "closed"}

_CARD_RE = re.compile(
    r'<a href="(/properties/[^"]+)" class="card-anchor"></a>.*?'
    r'<p class="card-text">([^<]+)</p>',
    re.S,
)
_STATE_IN_ADDR_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}")
_ADDR_PARSE_RE = re.compile(r"^(.*?),\s*([^,]+?),\s*([A-Z]{2})\s+(\d{5})")

_PRICE_RE = re.compile(r'class="property-price[^"]*">\s*([\d,]+)')
_SQFT_RE = re.compile(
    r'<span class="property-detail-value">([\d,]+)</span>'
    r'<span class="property-detail-label">sqft</span>'
)
_ACRE_RE = re.compile(
    r'<span class="property-detail-value">([\d.,]+)</span>'
    r'<span class="property-detail-label">acre lot</span>'
)
_DT_DD_RE = re.compile(r"<dt>([^<]+)</dt>\s*<dd>(.*?)</dd>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_BROKER_PHONE_RE = re.compile(r"(\+?\d[\d() .-]{7,}\d)")
_IMG_RE = re.compile(
    r"https://reallook\.com/storage/properties/[\w.-]+/images/[\w.-]+\.(?:jpe?g|png)",
    re.I,
)
# Each property's own sales brochure PDF, under a sibling /files/ path to
# /images/ above. NOT routed through the shared harvest_document_links() --
# its generic junk-denylist explicitly excludes "brochure" (a reasonable
# default for OTHER sources, where a brochure usually means generic
# marketing collateral), but here it's the one and only per-property
# document RealLook publishes, directly tied to this specific listing.
_PDF_RE = re.compile(
    r"https://reallook\.com/storage/properties/[\w.-]+/files/[\w.-]+\.pdf",
    re.I,
)

_KIND_MAP = {
    "single family": PropertyKind.SINGLE_FAMILY,
    "residential": PropertyKind.SINGLE_FAMILY,
    "condo": PropertyKind.CONDO,
    "townhouse": PropertyKind.TOWNHOUSE,
    "multi-family": PropertyKind.MULTI_FAMILY,
    "multi family": PropertyKind.MULTI_FAMILY,
    "commercial": PropertyKind.COMMERCIAL,
    "industrial": PropertyKind.COMMERCIAL,
    "land": PropertyKind.LAND,
    "mixed use": PropertyKind.MIXED,
}


def _clean(html_fragment: str) -> str:
    return _TAG_RE.sub("", html_fragment).strip()


def _money(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        v = float(raw.replace(",", ""))
        return v if v > 0 else None
    except ValueError:
        return None


async def _list_ids_for_state() -> list[tuple[str, str]]:
    """Page through the public property list; return [(href, address_text)]
    for every card whose OWN address line is in NC or SC. Cheap: this is
    the only step that touches out-of-state cards."""
    hits: list[tuple[str, str]] = []
    for page in range(1, _PAGES_CAP + 1):
        url = f"{_LIST_URL}?page={page}"
        try:
            html = await get_text(url, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("usmarshals.list_page_fail", page=page, error=str(exc)[:200])
            break
        if not html or len(html) < 500:
            break
        cards = _CARD_RE.findall(html)
        if not cards:
            break
        for href, addr in cards:
            sm = _STATE_IN_ADDR_RE.search(addr)
            if sm and sm.group(1) in _CORE_STATES:
                hits.append((href, addr.strip()))
        if len(cards) < 12:  # last page (12 cards/page, confirmed live)
            break
    return hits


def _parse_detail(html: str, href: str, list_addr: str) -> Listing | None:
    addr_m = _ADDR_PARSE_RE.match(list_addr)
    street = addr_m.group(1).strip() if addr_m else list_addr
    city = addr_m.group(2).strip() if addr_m else None
    state = addr_m.group(3) if addr_m else None
    zip_code = addr_m.group(4) if addr_m else None
    if state not in _CORE_STATES:
        return None

    fields: dict[str, str] = {}
    for label, value in _DT_DD_RE.findall(html):
        fields[label.strip()] = _clean(value)

    status = fields.get("Status", "").strip().lower()
    if status in _CLOSED_STATUSES:
        return None  # already sold/under contract/off market — not actionable

    price_m = _PRICE_RE.search(html)
    price = _money(price_m.group(1)) if price_m else None
    sqft_m = _SQFT_RE.search(html)
    sqft = _money(sqft_m.group(1)) if sqft_m else None
    acre_m = _ACRE_RE.search(html)
    acres = _money(acre_m.group(1)) if acre_m else None

    ptype_val = fields.get("Property Type", "").lower()
    kind = PropertyKind.UNKNOWN
    for key, k in _KIND_MAP.items():
        if key in ptype_val:
            kind = k
            break

    year_built = None
    yb = fields.get("Year Built", "")
    if yb.isdigit():
        year_built = int(yb)

    county = fields.get("County") or None
    if county and not county.lower().endswith("county"):
        county = f"{county} County"

    broker_raw = re.sub(r"\s+", " ", fields.get("Broker", "")).strip()
    broker_before_id = broker_raw.split("Broker ID:")[0].strip() if broker_raw else ""
    phone_m = _BROKER_PHONE_RE.search(broker_before_id)
    broker_phone = phone_m.group(1).strip() if phone_m else None
    broker_name = (
        broker_before_id[: phone_m.start()].strip() if phone_m else (broker_before_id or None)
    ) or None

    pid_m = re.search(r"/properties/([\w-]+)", href)
    pid = pid_m.group(1) if pid_m else href

    detail_url = f"{_BASE}{href}" if href.startswith("/") else href

    photos = sorted(set(_IMG_RE.findall(html)))
    doc_urls = sorted(set(_PDF_RE.findall(html)))

    li = Listing(
        source="national.usmarshals_realproperty",
        source_url=detail_url,
        listing_type=ListingType.REO,
        property_kind=kind,
        street_address=street or None,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        opening_bid=price,
        living_sqft=sqft,
        acreage=acres,
        year_built=year_built,
        case_number=f"usmarshals-reallook-{pid}",
        plaintiff="U.S. Marshals Service (via RealLook.com)",
        trustee=broker_name,
        description=f"US Marshals forfeited real property — {ptype_val or 'property'} "
                    f"({city}, {state})".strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"usmarshals": {
            "property_id": pid,
            "status": fields.get("Status"),
            "occupied": fields.get("Occupied"),
            "broker_name": broker_name,
            "broker_phone": broker_phone,
            "coordinates": fields.get("Coordinates"),
        }},
    )
    if photos:
        li.raw["images"] = {"real": photos}
    if doc_urls:
        stamp_documents(li, doc_urls)
    return li


class USMarshalsRealProperty(BaseScraper):
    slug = "national.usmarshals_realproperty"
    name = "US Marshals Service Real Property Forfeiture Sales (via RealLook.com)"
    category = "federal_reo"
    expected_min_count = 0  # Sporadic; often 0 in NC/SC
    requires_apify = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        try:
            hits = await _list_ids_for_state()
        except Exception as exc:
            log.warning("usmarshals.list_fail", error=str(exc)[:200])
            return []

        log.info("usmarshals.list_done", ncsc_hits=len(hits))
        out: list[Listing] = []
        for href, addr in hits:
            url = f"{_BASE}{href}" if href.startswith("/") else href
            try:
                html = await get_text(url, impersonate=True, timeout=30.0)
            except Exception as exc:
                log.warning("usmarshals.detail_fail", href=href, error=str(exc)[:200])
                continue
            try:
                li = _parse_detail(html, href, addr)
            except Exception as exc:
                log.warning("usmarshals.parse_fail", href=href, error=str(exc)[:200])
                continue
            if li is not None:
                out.append(li)

        log.info("usmarshals.done", count=len(out))
        return out
