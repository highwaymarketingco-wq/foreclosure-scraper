"""Meares Property Advisors — SC-Upstate real-estate / estate / tax auctions.

The firm runs live + online real-estate auctions across the upstate SC footprint
(Pickens / Easley / Simpsonville / Piedmont, etc.). The real site is
``https://www.mpa-sc.com/`` (``mearespropertyadvisors.com`` 301s there). It is a
BidWrangler-hosted company site whose two public inventory pages are:

  * ``/real-estate-auctions``  — live/online real-estate auctions
  * ``/real-estate-listings``  — brokered "buy it now" real-estate listings

Both are STATIC server-rendered HTML — a plain impersonated GET (curl-cffi Chrome
fingerprint) returns the full item markup, no browser render required (verified
live 2026-08-17). Each auction item is a ``div.row`` carrying:

  * ``h2 > a[href="/auctions/detail/<id>"]`` — title + the detail-page link, e.g.
    "26-059 Real Estate Auction: 117 Pine Lane, Pickens, SC 29671" (the address
    is embedded in the title AND in a dedicated maps anchor).
  * ``a[href^="https://maps.google.com/?q=<lat>,<lng>"]`` whose text is the full
    "street, city, ST zip, US" address — the cleanest address + lat/lng source.
  * a ``.list-unstyled`` clock list with "<Mon DD> @ <time> EDT (Start)" and
    "(End)" — the END is the sale close, used as ``sale_date``.
  * ``.easy-sold-badge`` — the advertised price / current-bid figure (kept in raw,
    NOT surfaced as opening_bid: on a reserve auction it is a list price, not a
    published opening bid).

County is not printed, so it is resolved from the parsed city via the shared
upstate city->county gazetteer (Pickens->Pickens, Easley->Pickens,
Simpsonville->Greenville, ...). Out-of-footprint rows are still emitted — the
orchestrator scope-filters at ingest; gating here would just hide a legit row.

Auction terms (buyer's premium, earnest-money deposit) live only on the detail
page, so each item's detail page is fetched best-effort to stash those in raw and
to run the shared document-artifact harvester (in case a listing ever links a
deed / contract PDF).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ..._upstate_city_to_county import upstate_county_for
from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.mpa-sc.com"
PAGES = (
    f"{BASE}/real-estate-auctions",
    f"{BASE}/real-estate-listings",
)

#: Best-effort per-item detail fetches (terms + doc harvest). The public
#: inventory is small (single digits), so this cap only guards a runaway.
_MAX_DETAIL_FETCH = 20

# "117 Pine Lane, Pickens, SC 29671, US" / "...SC 29671" — city is alpha, the
# trailing ", US" (and an optional +4 zip) are tolerated.
_ADDR_RE = re.compile(
    r"^(?P<street>.+?),\s*"
    r"(?P<city>[A-Za-z][A-Za-z .'\-]+?),\s*"
    r"(?P<state>[A-Za-z]{2})\s+"
    r"(?P<zip>\d{5})(?:-\d{4})?"
    r"(?:\s*,\s*US)?\s*$",
    re.I,
)
# The address as it appears after the colon in the item title, as a fallback.
_TITLE_ADDR_RE = re.compile(r":\s*(?P<addr>.+?)\s*$")
_LATLNG_RE = re.compile(r"[?&]q=(-?\d+\.\d+),\s*(-?\d+\.\d+)")
_MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# "Aug 28 @ 12:00pm EDT (End)" — capture the date + time separately.
_END_RE = re.compile(
    r"([A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s*\d{4})?)\s*@\s*([\d:]+\s*[ap]m)[^()]*\(End\)",
    re.I,
)

_LAND_RE = re.compile(r"\b(vacant\s+land|raw\s+land|lot|acreage|acres?|tract|parcel|farm|timber)\b", re.I)
_COMMERCIAL_RE = re.compile(r"\b(commercial|retail|office|warehouse|industrial|restaurant|storefront)\b", re.I)
_RESIDENTIAL_RE = re.compile(r"\b(home|house|residence|residential|bedroom|bath|cottage|cabin|condo|townhome|townhouse)\b", re.I)


def _parse_money(text: str | None) -> float | None:
    if not text:
        return None
    m = _MONEY_RE.search(text)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


def _parse_address(raw_addr: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """-> (street, city, state, zip). Street-only fallback when the tail is odd."""
    text = " ".join((raw_addr or "").split()).strip().rstrip(",")
    if not text:
        return None, None, None, None
    m = _ADDR_RE.match(text)
    if not m:
        return text or None, None, None, None
    return (
        (m.group("street") or "").strip() or None,
        (m.group("city") or "").strip() or None,
        (m.group("state") or "").strip().upper() or None,
        (m.group("zip") or "").strip() or None,
    )


def _infer_kind(text: str) -> PropertyKind:
    """Best-effort property kind from the title + description keywords."""
    t = text or ""
    if _COMMERCIAL_RE.search(t):
        return PropertyKind.COMMERCIAL
    if _RESIDENTIAL_RE.search(t):
        return PropertyKind.SINGLE_FAMILY
    if _LAND_RE.search(t):
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _parse_end_date(container) -> tuple[datetime | None, str | None]:
    """(sale_date, sale_time) from the '... @ <time> EDT (End)' clock line."""
    text = container.text(separator=" ", strip=True)
    m = _END_RE.search(text or "")
    if not m:
        return None, None
    date_part, time_part = m.group(1).strip(), m.group(2).strip()
    try:
        # The site prints no year; anchor missing fields (year + time-of-day) on
        # Jan-1 of the current year so only the parsed month/day survive — a bare
        # `datetime.utcnow()` default would smear the current wall-clock time onto
        # the sale date.
        dt = dateparser.parse(
            date_part, default=datetime(datetime.utcnow().year, 1, 1)
        )
    except (ValueError, TypeError, OverflowError):
        dt = None
    return dt, time_part or None


def _item_containers(tree: HTMLParser):
    """Yield (title, detail_href, container) for each auction/listing item.

    Anchored on the item ``h2`` (exactly one per item); the container is the
    nearest ancestor ``div.row`` that also holds the maps anchor, so we never
    double-count a nested column row.
    """
    for h2 in tree.css("h2"):
        a = h2.css_first("a[href*='auctions/detail'], a[href*='/listings/detail']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").strip()
        if not href:
            continue
        node = h2
        container = None
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            cls = (node.attributes.get("class") or "").split()
            if "row" in cls and node.css_first("a[href*='maps.google']") is not None:
                container = node
                break
        if container is None:
            container = h2.parent  # degrade gracefully rather than drop the row
        yield (h2.text(strip=True) or None), href, container


def _parse_item(title: str | None, detail_href: str, container, slug: str) -> Listing | None:
    detail_url = urljoin(BASE + "/", detail_href)

    # Address + lat/lng: prefer the dedicated maps anchor, fall back to the title.
    street = city = state = zip_code = None
    lat = lng = None
    maps_a = container.css_first("a[href*='maps.google']")
    if maps_a is not None:
        addr_text = maps_a.text(strip=True) or None
        if addr_text and addr_text.lower() != "map":
            street, city, state, zip_code = _parse_address(addr_text)
        lm = _LATLNG_RE.search(maps_a.attributes.get("href") or "")
        if lm:
            try:
                lat, lng = float(lm.group(1)), float(lm.group(2))
            except ValueError:
                lat = lng = None
    if not street and title:
        tm = _TITLE_ADDR_RE.search(title)
        if tm:
            street, city, state, zip_code = _parse_address(tm.group("addr"))

    state = state or "SC"
    county = upstate_county_for(city, state)

    sale_date, sale_time = _parse_end_date(container)

    # Advertised price / current-bid badge — kept in raw (a reserve-auction list
    # price, not a published opening bid).
    badge = container.css_first(".easy-sold-badge")
    price_badge = _parse_money(badge.text(strip=True)) if badge is not None else None

    # Description: the marketing blurb <p>, else the title.
    desc_p = container.css_first("div.margin-bottom-10, p")
    blurb = (desc_p.text(strip=True) if desc_p is not None else None) or None

    # Lot / sale number leads the title ("26-059 Real Estate Auction: ...").
    lot_no = None
    if title:
        lm = re.match(r"\s*([\dA-Za-z]+-[\dA-Za-z]+)\b", title)
        if lm:
            lot_no = lm.group(1)

    kind = _infer_kind(f"{title or ''} {blurb or ''}")

    desc_bits = [b for b in (title, blurb) if b]
    description = " — ".join(desc_bits) if desc_bits else None

    raw: dict = {"meares": {
        "lot_number": lot_no,
        "title": title,
        "price_badge": price_badge,
        "maps_lat": lat,
        "maps_lng": lng,
    }}

    return Listing(
        source=slug,
        source_url=detail_url,
        listing_type=ListingType.AUCTION,
        property_kind=kind,
        street_address=street,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        latitude=lat,
        longitude=lng,
        sale_date=sale_date,
        sale_time=sale_time,
        description=(description[:1000] if description else None),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


# Detail-page term extractors (best-effort; the detail page is BidWrangler HTML).
_PREMIUM_RE = re.compile(r"(?:Internet|Buyer'?s?)\s+Premium\s*:?\s*([\d.]+\s*%)", re.I)
_EARNEST_RE = re.compile(r"Earnest\s+Money\s+Deposit\s*:?\s*(\$?[\d,]+[^<\n]{0,40})", re.I)


async def _enrich_from_detail(li: Listing) -> None:
    """Fetch the item's detail page: stash auction terms in raw + harvest docs."""
    try:
        html = await get_text(li.source_url, impersonate=True, timeout=45.0)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        log.info("meares.detail_failed", url=li.source_url, error=str(exc)[:120])
        return
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    terms: dict = {}
    pm = _PREMIUM_RE.search(text)
    if pm:
        terms["buyers_premium"] = pm.group(1).strip()
    em = _EARNEST_RE.search(text)
    if em:
        terms["earnest_money_deposit"] = em.group(1).strip().rstrip(".")
    if terms:
        li.raw.setdefault("meares", {}).update(terms)
    # Wire the shared harvester so a real deed/contract scan is captured for OCR
    # the moment the firm posts one — but restrict to PDF/TIFF. The detail pages
    # carry only property photos + footer logos today (no deed docs), and the
    # generic harvester would otherwise stamp those images as OCR inputs.
    docs = [
        u for u in harvest_document_links(html, base_url=li.source_url)
        if re.search(r"\.(pdf|tiff?)(?:[?#]|$)", u, re.I)
    ]
    if docs:
        stamp_documents(li, docs)


class MearesAuctions(BaseScraper):
    slug = "counties_sc.meares_auctions"
    name = "Meares Property Advisors (SC Upstate real-estate auctions)"
    category = "county_court"
    requires_apify = False
    timeout_s = 180.0
    #: The firm routinely has 0-few live lots between sale cycles, so an empty
    #: run is legitimate — never a regression.
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()

        for page_url in PAGES:
            try:
                html = await get_text(page_url, impersonate=True, timeout=45.0)
            except Exception as exc:  # noqa: BLE001 — one page must not kill the run
                log.warning("meares.page_failed", url=page_url, error=str(exc)[:160])
                continue
            tree = HTMLParser(html)
            for title, href, container in _item_containers(tree):
                li = _parse_item(title, href, container, self.slug)
                if li is None:
                    continue
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                out.append(li)

        # Best-effort detail enrichment (terms + doc harvest), bounded + parallel.
        await asyncio.gather(
            *(_enrich_from_detail(li) for li in out[:_MAX_DETAIL_FETCH]),
            return_exceptions=True,
        )

        log.info("meares.counts", items=len(out))
        return out
