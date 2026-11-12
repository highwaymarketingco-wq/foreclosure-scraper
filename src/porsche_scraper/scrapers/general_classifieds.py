"""General-classifieds sites — Hemmings, ClassicCars.com, AutoTrader Classics.

Hemmings + ClassicCars are the two big classic/enthusiast classifieds in
the US. AutoTrader Classics merged into autotrader.com's classics
section. All three are server-rendered HTML; Hemmings also exposes
JSON-LD Vehicle blocks per card.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
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
from .cars_com import _walk_jsonld

log = logging.getLogger(__name__)


# ---------- Hemmings (Cloudflare/Kasada) ----------


class HemmingsScraper(BaseScraper):
    slug = "hemmings"
    name = "Hemmings"
    BASE = "https://www.hemmings.com"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, price_max: int = 45_000, max_pages: int = 5):
        self.year_min = year_min
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = (
                f"{self.BASE}/classifieds/cars-for-sale/porsche?type=Make"
                f"&MinYear={self.year_min}&MaxPrice={self.price_max}&page={page}"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("hemmings page %d: %s", page, exc)
                break
            listings = parse_hemmings_html(html)
            fresh = [l for l in listings if l.source_url not in seen]
            if not fresh:
                break
            seen.update(l.source_url for l in fresh)
            out.extend(fresh)
        return out


def parse_hemmings_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    # 1) JSON-LD Vehicle blocks (preferred).
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text() or "{}")
        except json.JSONDecodeError:
            continue
        for v in _walk_jsonld(data):
            url = v.get("url") or (v.get("offers") or {}).get("url")
            if not url:
                continue
            url = urljoin("https://www.hemmings.com", url)
            if url in seen:
                continue
            seen.add(url)
            title = v.get("name") or ""
            offers = v.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            mr = v.get("mileageFromOdometer") or {}
            listing = Listing(
                source="hemmings",
                source_url=url,
                listing_id=v.get("sku") or v.get("vehicleIdentificationNumber"),
                vin=v.get("vehicleIdentificationNumber"),
                title=title,
                year=int(v["vehicleModelDate"]) if str(v.get("vehicleModelDate") or "").isdigit() else parse_year(title),
                model=v.get("model"),
                price_usd=parse_price(offers.get("price")),
                mileage=parse_miles(mr.get("value")) if isinstance(mr, dict) else None,
                photo_url=(v.get("image") or [None])[0] if isinstance(v.get("image"), list) else v.get("image"),
                title_status=infer_title_status(title),
                seller_type="dealer",
                raw={"jsonld": v},
            )
            listing.drivable = infer_drivable(title, listing.title_status)
            out.append(listing)
    if out:
        return out
    # 2) HTML fallback.
    for c in tree.css(".listingContainer, .listing-card, article[class*='listing']"):
        a = c.css_first(".listing-title a") or c.css_first("a[href*='/classifieds/']")
        if not a:
            continue
        href = a.attributes.get("href")
        if not href:
            continue
        url = urljoin("https://www.hemmings.com", href)
        if url in seen:
            continue
        seen.add(url)
        title = a.text(strip=True)
        price_node = c.css_first(".price") or c.css_first(".listing-price")
        loc_node = c.css_first(".location")
        img = c.css_first("img")
        listing = Listing(
            source="hemmings",
            source_url=url,
            title=title,
            year=parse_year(title),
            price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
            location=loc_node.text(strip=True) if loc_node else None,
            photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
            title_status=infer_title_status(title),
            seller_type="dealer",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


# ---------- ClassicCars.com ----------


class ClassicCarsDotComScraper(BaseScraper):
    slug = "classiccars_com"
    name = "ClassicCars.com"
    BASE = "https://classiccars.com"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, price_max: int = 45_000, max_pages: int = 10):
        self.year_min = year_min
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = (
                f"{self.BASE}/listings/find?Make=Porsche"
                f"&MinYear={self.year_min}&MaxPrice={self.price_max}&p={page}"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("classiccars page %d: %s", page, exc)
                break
            listings = parse_classiccars_html(html)
            fresh = [l for l in listings if l.source_url not in seen]
            if not fresh:
                break
            seen.update(l.source_url for l in fresh)
            out.extend(fresh)
        return out


def parse_classiccars_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for c in tree.css(".listing-card, .featured-listing, article.car-listing"):
        a = c.css_first("a[href*='/listings/view/']") or c.css_first("h3 a")
        if not a:
            continue
        href = a.attributes.get("href")
        if not href:
            continue
        url = urljoin("https://classiccars.com", href)
        if url in seen:
            continue
        seen.add(url)
        title = a.text(strip=True)
        price_node = c.css_first(".price") or c.css_first(".listing-price")
        miles_node = c.css_first(".mileage")
        loc_node = c.css_first(".location") or c.css_first(".listing-location")
        img = c.css_first("img")
        listing = Listing(
            source="classiccars_com",
            source_url=url,
            title=title,
            year=parse_year(title),
            price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
            mileage=parse_miles(miles_node.text(strip=True)) if miles_node else None,
            location=loc_node.text(strip=True) if loc_node else None,
            photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
            title_status=infer_title_status(title),
            seller_type="private",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


# ---------- AutoTrader Classics ----------


class AutoTraderClassicsScraper(BaseScraper):
    slug = "autotrader_classics"
    name = "AutoTrader Classics"
    BASE = "https://classics.autotrader.com"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, price_max: int = 45_000, max_pages: int = 5):
        self.year_min = year_min
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = (
                f"{self.BASE}/find-cars-for-sale-by-make/porsche/"
                f"?MinYear={self.year_min}&MaxPrice={self.price_max}"
                f"&firstRecord={(page - 1) * 25}&numRecords=25"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("autotrader_classics page %d: %s", page, exc)
                break
            listings = parse_atc_html(html)
            fresh = [l for l in listings if l.source_url not in seen]
            if not fresh:
                break
            seen.update(l.source_url for l in fresh)
            out.extend(fresh)
        return out


def parse_atc_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for c in tree.css(".listing-card, article.listing, .vehicle-card"):
        a = c.css_first("a[href*='/listing/']") or c.css_first("h3 a")
        if not a:
            continue
        href = a.attributes.get("href")
        if not href:
            continue
        url = urljoin("https://classics.autotrader.com", href)
        if url in seen:
            continue
        seen.add(url)
        title = a.text(strip=True)
        price_node = c.css_first(".price") or c.css_first(".listing-price")
        miles_node = c.css_first(".mileage")
        loc_node = c.css_first(".location")
        img = c.css_first("img")
        listing = Listing(
            source="autotrader_classics",
            source_url=url,
            title=title,
            year=parse_year(title),
            price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
            mileage=parse_miles(miles_node.text(strip=True)) if miles_node else None,
            location=loc_node.text(strip=True) if loc_node else None,
            photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
            title_status=infer_title_status(title),
            seller_type="dealer",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out
