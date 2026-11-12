"""cars.com — Porsche search.

Search URL pattern:
    https://www.cars.com/shopping/results/
        ?stock_type=used
        &makes[]=porsche
        &list_price_max=45000
        &year_min=2014
        &page_size=100
        &page=N

Cars.com server-renders results AND embeds a JSON-LD ItemList of all the
Vehicle objects on the page. We parse the JSON-LD first (it has clean
year/make/model/price/mileage) and fall back to HTML selectors if it's
missing. They also expose a separate "salvage" filter we union in via a
second pass without `list_price_max`, restricted to `condition=salvage`.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_text, fetch_text_stealth
from ..models import (
    Listing,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://www.cars.com"

# Target only the wanted models. Cars.com's `models[]=` is an inclusive
# whitelist — using it naturally drops Cayenne/Panamera/Macan that
# otherwise dominate "Porsche" search hits in the budget range.
WANTED_MODEL_SLUGS = (
    "porsche-911",
    "porsche-718_cayman",
    "porsche-cayman",
    "porsche-718_boxster",
    "porsche-boxster",
    "porsche-918_spyder",
)


def _build_url(
    *, year_min: int, price_max: int | None, page: int, page_size: int = 100,
    models: tuple[str, ...] = WANTED_MODEL_SLUGS,
) -> str:
    parts = [
        "stock_type=used",
        "makes[]=porsche",
        *[f"models[]={m}" for m in models],
        f"year_min={year_min}",
        f"page_size={page_size}",
        f"page={page}",
        "sort=list_price-asc",
    ]
    if price_max is not None:
        parts.append(f"list_price_max={price_max}")
    return f"{BASE}/shopping/results/?" + "&".join(parts)


def _extract_jsonld(html: str) -> list[dict]:
    """Return all JSON-LD blobs of @type Vehicle (or items inside ItemList)."""
    out: list[dict] = []
    tree = HTMLParser(html)
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _walk_jsonld(data):
            out.append(item)
    return out


def _walk_jsonld(data) -> Iterable[dict]:
    if isinstance(data, list):
        for d in data:
            yield from _walk_jsonld(d)
        return
    if not isinstance(data, dict):
        return
    t = data.get("@type")
    if t == "Vehicle":
        yield data
    if t == "ItemList":
        for item in data.get("itemListElement") or []:
            inner = item.get("item") if isinstance(item, dict) else None
            if isinstance(inner, dict) and inner.get("@type") == "Vehicle":
                yield inner


def _listing_from_jsonld(v: dict) -> Listing | None:
    url = v.get("url") or v.get("offers", {}).get("url")
    if not url:
        return None
    url = urljoin(BASE, url)
    title = v.get("name") or ""
    year = v.get("vehicleModelDate") or v.get("modelDate")
    try:
        year = int(year) if year else parse_year(title)
    except (TypeError, ValueError):
        year = parse_year(title)
    offers = v.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = parse_price(offers.get("price"))
    miles = None
    mr = v.get("mileageFromOdometer") or {}
    if isinstance(mr, dict):
        miles = parse_miles(mr.get("value"))
    model = v.get("model") or ""
    listing = Listing(
        source="cars_com",
        source_url=url,
        listing_id=v.get("vehicleIdentificationNumber") or v.get("sku"),
        vin=v.get("vehicleIdentificationNumber"),
        title=title,
        year=year,
        model=str(model) if model else None,
        price_usd=price,
        mileage=miles,
        photo_url=(v.get("image") or [None])[0] if isinstance(v.get("image"), list) else v.get("image"),
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"jsonld": v},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


_CARD_SELECTOR = ".vehicle-card"


def _listing_from_fuse_card(card) -> Listing | None:
    """Parse a `<fuse-card data-vehicle-details='{...}'>` element.

    Cars.com (as of 2026-05) renders each result as a fuse-card web
    component with the full listing record JSON-encoded in this attribute.
    """
    details_raw = card.attributes.get("data-vehicle-details")
    if not details_raw:
        return None
    try:
        d = json.loads(details_raw)
    except json.JSONDecodeError:
        return None
    listing_id = d.get("listingId") or card.attributes.get("data-listing-id")
    if not listing_id:
        return None
    url = urljoin(BASE, f"/vehicledetail/{listing_id}/")
    year = d.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    model = d.get("model") or ""
    trim = d.get("trim") or ""
    make = d.get("make") or "Porsche"
    title = " ".join(filter(None, [str(year or ""), make, model, trim])).strip()
    seller = d.get("seller") or {}
    listing = Listing(
        source="cars_com",
        source_url=url,
        listing_id=str(listing_id),
        vin=d.get("vin"),
        title=title,
        year=year,
        model=model or None,
        trim=trim or None,
        price_usd=parse_price(d.get("price")),
        mileage=parse_miles(d.get("mileage")),
        location=seller.get("zip"),
        photo_url=d.get("primaryThumbnail"),
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"cars_com": d},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _listing_from_card(card) -> Listing | None:
    a = card.css_first("a.vehicle-card-link") or card.css_first("a[href*='/vehicledetail/']")
    if not a:
        return None
    href = a.attributes.get("href")
    if not href:
        return None
    url = urljoin(BASE, href)
    title_node = card.css_first(".title") or card.css_first("h2")
    title = title_node.text(strip=True) if title_node else ""
    price_node = card.css_first(".primary-price")
    price = parse_price(price_node.text(strip=True)) if price_node else None
    miles_node = card.css_first(".mileage")
    miles = parse_miles(miles_node.text(strip=True)) if miles_node else None
    loc_node = card.css_first(".miles-from-user") or card.css_first(".dealer-name")
    img_node = card.css_first("img")
    img = (
        img_node.attributes.get("src")
        or img_node.attributes.get("data-src")
        if img_node
        else None
    )
    stock = card.attributes.get("data-listing-id") or card.attributes.get("id")
    listing = Listing(
        source="cars_com",
        source_url=url,
        listing_id=stock,
        title=title,
        year=parse_year(title),
        price_usd=price,
        mileage=miles,
        location=loc_node.text(strip=True) if loc_node else None,
        photo_url=img,
        title_status=infer_title_status(title),
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def parse_results_html(html: str) -> list[Listing]:
    """Parse one cars.com search-results page into Listings.

    Order of fallbacks:
      1. <fuse-card data-vehicle-details='{...}'>  (current 2026-05 markup)
      2. JSON-LD ItemList of Vehicle objects (older template)
      3. .vehicle-card HTML selectors (oldest template)
    """
    tree = HTMLParser(html)
    seen_urls: set[str] = set()
    out: list[Listing] = []
    for card in tree.css("fuse-card[data-vehicle-details]"):
        listing = _listing_from_fuse_card(card)
        if listing and listing.source_url not in seen_urls:
            seen_urls.add(listing.source_url)
            out.append(listing)
    if out:
        return out
    for v in _extract_jsonld(html):
        listing = _listing_from_jsonld(v)
        if listing and listing.source_url not in seen_urls:
            seen_urls.add(listing.source_url)
            out.append(listing)
    if out:
        return out
    for card in tree.css(_CARD_SELECTOR):
        listing = _listing_from_card(card)
        if listing and listing.source_url not in seen_urls:
            seen_urls.add(listing.source_url)
            out.append(listing)
    return out


_PAGINATION_TOTAL_RE = re.compile(r'"totalNumberOfPages"\s*:\s*(\d+)')


def _total_pages(html: str) -> int:
    m = _PAGINATION_TOTAL_RE.search(html)
    return min(int(m.group(1)), 20) if m else 1  # Cap at 20 pages defensively.


class CarsComScraper(BaseScraper):
    slug = "cars_com"
    name = "Cars.com"
    timeout_s = 480.0  # Up from 120s — Scrapling fallback can take 30s/page.

    def __init__(self, *, year_min: int = 2014, price_max: int | None = 45000, max_pages: int = 20):
        self.year_min = year_min
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        # Pass 1: regular price-capped results.
        out.extend(await self._fetch_filtered(price_max=self.price_max))
        # Pass 2: salvage-condition results regardless of price.
        out.extend(await self._fetch_filtered(price_max=None, extra="&condition=salvage"))
        return out

    async def _fetch_filtered(self, *, price_max: int | None, extra: str = "") -> list[Listing]:
        out: list[Listing] = []
        page = 1
        total = 1
        while page <= min(total, self.max_pages):
            url = _build_url(year_min=self.year_min, price_max=price_max, page=page) + extra
            try:
                html = await fetch_text(url, timeout=45)
            except Exception as exc_plain:  # noqa: BLE001
                # Cars.com rate-limits with 503; retry through curl-cffi + Scrapling.
                log.info("cars_com page %d plain fetch failed (%s) — trying stealth", page, exc_plain)
                try:
                    html = await fetch_text_stealth(url, timeout=45, fallback_to_render=True)
                except Exception as exc_stealth:  # noqa: BLE001
                    log.warning("cars_com page %d both fetchers failed: %s", page, exc_stealth)
                    break
            if page == 1:
                total = _total_pages(html)
            page_listings = parse_results_html(html)
            if not page_listings:
                break
            out.extend(page_listings)
            page += 1
        return out
