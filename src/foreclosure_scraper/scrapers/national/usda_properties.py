"""USDA Rural Development eligible homes + REO resales — usdaproperties.com.

usdaproperties.com aggregates USDA-eligible / Rural-Development resale homes
nationwide behind clean, server-rendered per-property URLs:

    https://usdaproperties.com/property/<state>/<zip>/<id>/

The site indexes inventory by county at

    https://www.usdaproperties.com/property/sc/county/<county-slug>/

and each county page server-renders a grid (``div#hgGrid``) of ``div.card``
tiles — no JS required. Every tile carries the full record in HTML +
data-attributes:

    <div class="card" data-price="55000" data-beds="3" data-baths="1.0"
         data-type="home" data-elig="1" data-zip="29372">
      <a class="lc-imgwrap" href="/property/sc/29372/6461163737/"> ...img... </a>
      <a class="lc-body-link" href="/property/sc/29372/6461163737/"><div class="cbody">
        <div class="cprice">$55,000</div>
        <div class="caddr">131 Sycamore St</div>
        <div class="cfacts">3 bd &middot; 1 ba &middot; 1,040 sqft</div>
      </div></a>
    </div>

Because we fetch by county page, every tile on a page is definitively in that
county, so we tag ``county`` directly (no derivation guesswork) and stay inside
the in-footprint SC scope. We only crawl the upstate-SC footprint counties
(config.SC_COUNTIES); the orchestrator scope-filter would drop anything else
anyway. REO listings carry no sale date, so the slug is in
main.DATELESS_OK_SOURCES.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.usdaproperties.com"

# Upstate-SC footprint counties (mirrors config.SC_COUNTIES). The site slugs are
# the lowercase county name. Every card on a county page belongs to that county.
SC_COUNTY_SLUGS = (
    "spartanburg",
    "anderson",
    "pickens",
    "oconee",
    "cherokee",
    "union",
    "laurens",
)

_PRICE_RE = re.compile(r"([\d,]+)")
_SQFT_RE = re.compile(r"([\d,]+)\s*sqft", re.IGNORECASE)
_HREF_RE = re.compile(r"/property/([a-z]{2})/(\d{5})/(\d+)/")


def _kind(data_type: str | None, facts: str | None) -> PropertyKind:
    t = (data_type or "").strip().lower()
    if t == "land" or (facts and "land" in facts.lower()):
        return PropertyKind.LAND
    if facts:
        f = facts.lower()
        if "condo" in f:
            return PropertyKind.CONDO
        if "town" in f:
            return PropertyKind.TOWNHOUSE
        if "manufactured" in f or "mobile" in f:
            return PropertyKind.MOBILE
    if t == "home":
        # USDA RD Section 502 inventory is single-family housing.
        return PropertyKind.SINGLE_FAMILY
    return PropertyKind.UNKNOWN


def _num(val: str | None) -> float | None:
    if not val:
        return None
    m = _PRICE_RE.search(val)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_card(card, county: str, slug: str) -> Listing | None:
    """Parse a single ``div.card`` tile. Returns None for unparseable rows."""
    link = card.css_first("a[href*='/property/']")
    href = link.attributes.get("href") if link is not None else None
    if not href:
        return None
    m = _HREF_RE.search(href)
    if not m:
        return None
    st, zip_code, prop_id = m.group(1).upper(), m.group(2), m.group(3)
    if st != "SC":
        return None
    source_url = f"https://usdaproperties.com/property/sc/{zip_code}/{prop_id}/"

    addr_node = card.css_first("div.caddr")
    street = addr_node.text(strip=True) if addr_node is not None else None
    if not street:
        img = card.css_first("img[alt]")
        street = img.attributes.get("alt") if img is not None else None
    street = re.sub(r"\s+", " ", street).strip() if street else None
    if not street:
        return None

    price_node = card.css_first("div.cprice")
    price = _num(price_node.text(strip=True)) if price_node is not None else None
    if price is None:
        price = _num(card.attributes.get("data-price"))

    facts_node = card.css_first("div.cfacts")
    facts = (
        re.sub(r"\s+", " ", facts_node.text(separator=" ", strip=True))
        if facts_node is not None
        else None
    )
    sqft = None
    if facts:
        sm = _SQFT_RE.search(facts)
        if sm:
            try:
                sqft = float(sm.group(1).replace(",", ""))
            except ValueError:
                sqft = None

    beds = _num(card.attributes.get("data-beds"))
    baths = _num(card.attributes.get("data-baths"))
    data_type = card.attributes.get("data-type")
    img_node = card.css_first("img[src]")
    img_url = img_node.attributes.get("src") if img_node is not None else None
    photos = [img_url] if img_url and img_url.startswith("http") else []

    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=ListingType.REO,
        property_kind=_kind(data_type, facts),
        state="SC",
        county=county.title(),
        zip_code=zip_code,
        street_address=street,
        opening_bid=price,
        living_sqft=sqft,
        bedrooms=beds,
        bathrooms=baths,
        description=" ".join(
            p for p in ("USDA Rural Development eligible / REO resale.", facts) if p
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "usda_property_id": prop_id,
            "usda_data_type": data_type,
            "usda_eligible": card.attributes.get("data-elig") == "1",
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "facts": facts,
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_county(slug_scraper: str, county_slug: str) -> list[Listing]:
    url = f"{BASE}/property/sc/county/{county_slug}/"
    try:
        html = await get_text(url, impersonate=True, timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("usda_properties.fetch_failed", county=county_slug, error=str(exc)[:200])
        return []
    if not html or len(html) < 5000:
        return []
    tree = HTMLParser(html)
    cards = tree.css("div#hgGrid div.card") or tree.css("div.card")
    out: list[Listing] = []
    for card in cards:
        try:
            li = _parse_card(card, county_slug, slug_scraper)
        except Exception:  # noqa: BLE001
            continue
        if li is not None:
            out.append(li)
    log.info("usda_properties.county_done", county=county_slug, cards=len(cards), kept=len(out))
    return out


class USDAProperties(BaseScraper):
    slug = "national.usda_properties"
    name = "USDA Properties (Rural Development eligible / REO, SC)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for county_slug in SC_COUNTY_SLUGS:
            try:
                rows = await _fetch_county(self.slug, county_slug)
            except Exception as exc:  # noqa: BLE001
                log.warning("usda_properties.county_failed", county=county_slug, error=str(exc)[:200])
                continue
            for li in rows:
                pid = li.raw.get("usda_property_id")
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                out.append(li)
        log.info("usda_properties.done", total=len(out))
        return out
