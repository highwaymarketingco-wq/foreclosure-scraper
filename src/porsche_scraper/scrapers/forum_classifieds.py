"""Forum classifieds — Rennlist + 6Speed Online.

Both run vBulletin 4 on Internet Brands' shared infra; thread lists use
identical markup. Each thread title typically contains the year + model
+ price in plain text, e.g. "FS: 2016 Cayman GT4 — $89,000 — clean
title — 24k miles".

Rennlist classifieds index:    https://rennlist.com/forums/porsche-classifieds/
6Speed Online classifieds idx: https://www.6speedonline.com/forums/porsche-classifieds/

Pagination /page2/, /page3/. Some sub-forums are members-only; we crawl
the public top-level index only. Light Cloudflare — uses stealth
transport.
"""
from __future__ import annotations

import logging
import re
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

log = logging.getLogger(__name__)


# Thread titles often follow: "FS [region]: 2014 911 — $35,000 — 50k mi"
_PRICE_IN_TITLE_RE = re.compile(r"\$\s*([\d,]+)")


def _listing_from_thread(li, base_url: str, source: str) -> Listing | None:
    link = li.css_first("a.title") or li.css_first("a[href*='showthread']") or li.css_first("h3 a")
    if not link:
        return None
    href = link.attributes.get("href")
    if not href:
        return None
    title = link.text(strip=True)
    if not title or not any(kw in title.lower() for kw in ("porsche", "911", "cayman", "boxster", "718", "924", "928", "944", "968")):
        return None
    price = parse_price(title)
    miles = parse_miles(title)
    listing = Listing(
        source=source,
        source_url=urljoin(base_url, href),
        title=title,
        year=parse_year(title),
        price_usd=price,
        mileage=miles,
        title_status=infer_title_status(title),
        seller_type="private",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


def parse_thread_list(html: str, base_url: str, source: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for sel in ("li.threadbit", "tr.thread", "div.thread", ".thread-item"):
        rows = tree.css(sel)
        if rows:
            break
    else:
        rows = []
    for li in rows:
        listing = _listing_from_thread(li, base_url, source)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class RennlistScraper(BaseScraper):
    slug = "rennlist"
    name = "Rennlist Classifieds"
    BASE = "https://rennlist.com"

    def __init__(self, *, max_pages: int = 5):
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            url = (
                f"{self.BASE}/forums/porsche-classifieds/"
                if page == 1
                else f"{self.BASE}/forums/porsche-classifieds/index{page}.html"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("rennlist page %d: %s", page, exc)
                break
            listings = parse_thread_list(html, self.BASE, self.slug)
            if not listings:
                break
            out.extend(listings)
        return out


class SixSpeedOnlineScraper(BaseScraper):
    slug = "6speedonline"
    name = "6Speed Online Classifieds"
    BASE = "https://www.6speedonline.com"

    def __init__(self, *, max_pages: int = 5):
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            url = (
                f"{self.BASE}/forums/porsche-classifieds/"
                if page == 1
                else f"{self.BASE}/forums/porsche-classifieds/index{page}.html"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("6speedonline page %d: %s", page, exc)
                break
            listings = parse_thread_list(html, self.BASE, self.slug)
            if not listings:
                break
            out.extend(listings)
        return out


class PcaMartScraper(BaseScraper):
    """Porsche Club of America classifieds. List view is public; detail
    pages require PCA membership login for contact info.

    URL: https://classifieds.pca.org/listings?category=cars&make=Porsche
    """

    slug = "pca_mart"
    name = "PCA Mart"
    BASE = "https://classifieds.pca.org"

    def __init__(self, *, year_min: int = 2014, max_pages: int = 5):
        self.year_min = year_min
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            url = (
                f"{self.BASE}/listings?category=cars&make=Porsche"
                f"&year_min={self.year_min}&page={page}"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("pca_mart page %d: %s", page, exc)
                break
            tree = HTMLParser(html)
            cards = tree.css(".listing-card") or tree.css("article.listing")
            if not cards:
                break
            seen: set[str] = set()
            for c in cards:
                a = c.css_first("a[href*='/listings/']") or c.css_first("h3 a")
                if not a:
                    continue
                href = a.attributes.get("href")
                if not href:
                    continue
                url_full = urljoin(self.BASE, href)
                if url_full in seen:
                    continue
                seen.add(url_full)
                title = a.text(strip=True)
                price_node = c.css_first(".listing-card__price") or c.css_first(".price")
                loc_node = c.css_first(".listing-card__location") or c.css_first(".location")
                miles_node = c.css_first(".listing-card__mileage") or c.css_first(".mileage")
                img = c.css_first("img")
                listing = Listing(
                    source=self.slug,
                    source_url=url_full,
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
