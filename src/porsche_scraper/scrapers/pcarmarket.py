"""PCARMARKET — Porsche-focused online auctions + fixed-price marketplace.

URLs:
- Auctions:   https://www.pcarmarket.com/auctions?search=porsche&status=active
- Marketplace: https://www.pcarmarket.com/marketplace?search=porsche

Server-rendered HTML (Symfony). Cards: `.auction-list-item` / `.car-tile`.
Sits behind a light Cloudflare layer — uses the stealth transport.
"""
from __future__ import annotations

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

log = logging.getLogger(__name__)

BASE = "https://www.pcarmarket.com"


def _listing_from_card(card) -> Listing | None:
    link = card.css_first(".auction-title a") or card.css_first("h3 a") or card.css_first("a[href*='/auction/']")
    if not link:
        return None
    href = link.attributes.get("href")
    if not href:
        return None
    url = urljoin(BASE, href)
    title = link.text(strip=True)
    bid_node = card.css_first(".current-bid .amount") or card.css_first(".current-bid") or card.css_first(".price")
    img = card.css_first("img")
    reserve_node = card.css_first(".reserve-status")
    miles_node = card.css_first(".car-tile-mileage") or card.css_first(".mileage")
    loc_node = card.css_first(".car-tile-location") or card.css_first(".location")
    listing = Listing(
        source="pcarmarket",
        source_url=url,
        title=title,
        year=parse_year(title),
        current_bid_usd=parse_price(bid_node.text(strip=True)) if bid_node else None,
        mileage=parse_miles(miles_node.text(strip=True)) if miles_node else None,
        location=loc_node.text(strip=True) if loc_node else None,
        photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
        title_status=infer_title_status(title + " " + (reserve_node.text(strip=True) if reserve_node else "")),
        seller_type="auction",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


def parse_results_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for sel in (".auction-list-item", ".car-tile", "div[class*='auction-list']"):
        cards = tree.css(sel)
        if cards:
            break
    else:
        cards = []
    for card in cards:
        listing = _listing_from_card(card)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class PCarMarketScraper(BaseScraper):
    slug = "pcarmarket"
    name = "PCARMARKET"

    def __init__(self, *, max_pages: int = 5):
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for path in (
            "/auctions?search=porsche&status=active",
            "/auctions?search=porsche&status=ended",
            "/marketplace?search=porsche",
        ):
            for page in range(1, self.max_pages + 1):
                url = urljoin(BASE, path) + f"&page={page}"
                try:
                    html = await fetch_text_stealth(url, timeout=60)
                except Exception as exc:  # noqa: BLE001
                    log.warning("pcarmarket %s page %d: %s", path, page, exc)
                    break
                listings = parse_results_html(html)
                if not listings:
                    break
                out.extend(listings)
        return out
