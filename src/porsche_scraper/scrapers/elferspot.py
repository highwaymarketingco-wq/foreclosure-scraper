"""Elferspot — German/EU Porsche marketplace, ~5,000 cars on average.

URL: https://elferspot.com/en/sportscar/porsche/?priceTo={EUR}&yearFrom=2014

EUR pricing — we approximate USD via a static conversion (€1 ≈ $1.08).
Use env `EUR_TO_USD` to override at runtime. Multilingual site;
we hit the `/en/` locale.

No Cloudflare challenge; light bot defenses. WordPress + WooCommerce.
"""
from __future__ import annotations

import logging
import os
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

BASE = "https://elferspot.com"


def _eur_to_usd() -> float:
    try:
        return float(os.environ.get("EUR_TO_USD", "1.08"))
    except ValueError:
        return 1.08


def _listing_from_card(card, fx: float) -> Listing | None:
    link = card.css_first(".listing-title a") or card.css_first("a[href*='/sportscar/']") or card.css_first("h2 a")
    if not link:
        return None
    href = link.attributes.get("href")
    if not href:
        return None
    title = link.text(strip=True)
    price_node = card.css_first(".listing-price .amount") or card.css_first(".price") or card.css_first(".listing-price")
    price_eur = parse_price(price_node.text(strip=True)) if price_node else None
    price_usd = price_eur * fx if price_eur is not None else None
    miles_node = card.css_first(".listing-meta__mileage") or card.css_first(".mileage")
    miles = parse_miles(miles_node.text(strip=True)) if miles_node else None
    loc_node = card.css_first(".listing-meta__country") or card.css_first(".country") or card.css_first(".location")
    img = card.css_first("img")
    listing = Listing(
        source="elferspot",
        source_url=urljoin(BASE, href),
        title=title,
        year=parse_year(title),
        price_usd=price_usd,
        mileage=miles,
        location=loc_node.text(strip=True) if loc_node else None,
        photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"price_eur": price_eur},
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


def parse_results_html(html: str, *, fx: float | None = None) -> list[Listing]:
    fx = fx if fx is not None else _eur_to_usd()
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for sel in ("article.elferspot-listing", ".product-item", ".car-listing-item",
                "article[class*='listing']"):
        cards = tree.css(sel)
        if cards:
            break
    else:
        cards = []
    for card in cards:
        listing = _listing_from_card(card, fx)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class ElferspotScraper(BaseScraper):
    slug = "elferspot"
    name = "Elferspot"

    def __init__(self, *, year_min: int = 2014, max_pages: int = 10):
        self.year_min = year_min
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            url = (
                f"{BASE}/en/sportscar/porsche/"
                f"?yearFrom={self.year_min}&page={page}"
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("elferspot page %d: %s", page, exc)
                break
            listings = parse_results_html(html)
            if not listings:
                break
            out.extend(listings)
        return out
