"""carsforsale.com — Porsche listings.

URL:
    https://www.carsforsale.com/used-porsche-for-sale?maxPrice=45000&yearMin=2014

Server-rendered HTML, JSON-LD Vehicle blocks present. Lightweight bot
protection — uses the stealth transport just in case.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_text_stealth
from ..models import (
    Listing,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)
from .cars_com import _walk_jsonld  # JSON-LD walker is generic enough to reuse.

log = logging.getLogger(__name__)

BASE = "https://www.carsforsale.com"


def _listing_from_jsonld(v: dict) -> Listing | None:
    url = v.get("url") or (v.get("offers") or {}).get("url")
    if not url:
        return None
    url = urljoin(BASE, url)
    title = v.get("name") or ""
    offers = v.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    miles = None
    mr = v.get("mileageFromOdometer") or {}
    if isinstance(mr, dict):
        miles = parse_miles(mr.get("value"))
    listing = Listing(
        source="carsforsale",
        source_url=url,
        listing_id=v.get("vehicleIdentificationNumber") or v.get("sku"),
        vin=v.get("vehicleIdentificationNumber"),
        title=title,
        year=int(v["vehicleModelDate"]) if str(v.get("vehicleModelDate") or "").isdigit() else parse_year(title),
        model=v.get("model"),
        price_usd=parse_price(offers.get("price")),
        mileage=miles,
        photo_url=(v.get("image") or [None])[0] if isinstance(v.get("image"), list) else v.get("image"),
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"jsonld": v},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _listing_from_tile(tile) -> Listing | None:
    a = tile.css_first("a[href*='/vehicle/']") or tile.css_first("a[href]")
    if not a:
        return None
    href = a.attributes.get("href")
    if not href:
        return None
    title_node = tile.css_first(".hrf-tile-title") or tile.css_first("h3")
    price_node = tile.css_first(".hrf-tile-price") or tile.css_first(".price")
    miles_node = tile.css_first(".hrf-tile-miles") or tile.css_first(".mileage")
    loc_node = tile.css_first(".hrf-tile-location") or tile.css_first(".location")
    img = tile.css_first("img")
    title = title_node.text(strip=True) if title_node else a.text(strip=True)
    listing = Listing(
        source="carsforsale",
        source_url=urljoin(BASE, href),
        title=title,
        year=parse_year(title),
        price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
        mileage=parse_miles(miles_node.text(strip=True)) if miles_node else None,
        location=loc_node.text(strip=True) if loc_node else None,
        photo_url=(img.attributes.get("data-src") or img.attributes.get("src")) if img else None,
        title_status=infer_title_status(title),
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def parse_results_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text() or "")
        except json.JSONDecodeError:
            continue
        for v in _walk_jsonld(data):
            listing = _listing_from_jsonld(v)
            if listing and listing.source_url not in seen:
                seen.add(listing.source_url)
                out.append(listing)
    if out:
        return out
    for tile in tree.css(".hrf-tile, .vehicle-card, .listing-tile"):
        listing = _listing_from_tile(tile)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class CarsForSaleScraper(BaseScraper):
    slug = "carsforsale"
    name = "CarsForSale.com"

    def __init__(self, *, year_min: int = 2014, price_max: int | None = 45000, max_pages: int = 10):
        self.year_min = year_min
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            params = [f"yearMin={self.year_min}", f"page={page}"]
            if self.price_max is not None:
                params.append(f"maxPrice={self.price_max}")
            url = f"{BASE}/used-porsche-for-sale?" + "&".join(params)
            try:
                html = await fetch_text_stealth(url, timeout=45)
            except Exception as exc:  # noqa: BLE001
                log.warning("carsforsale page %d failed: %s", page, exc)
                break
            listings = parse_results_html(html)
            if not listings:
                break
            out.extend(listings)
        return out
