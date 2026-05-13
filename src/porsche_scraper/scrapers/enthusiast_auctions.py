"""Enthusiast-auction sites (clean-title collector cars).

Hagerty, Collecting Cars, TheMarket (Bonhams), AutoHunter, Broad Arrow,
Iconic Auctioneers. These all run nearly-identical lot-grid templates,
so we share one parser config-driven per site.

Bot-protection levels vary; the heavier ones (CollectingCars, AutoHunter,
BroadArrow) need a residential proxy plus the stealth transport.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable
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


@dataclass(frozen=True)
class SiteConfig:
    slug: str
    name: str
    base: str
    search_url_template: str  # accepts {page}; optionally {year_min}, {price_max}
    card_selectors: tuple[str, ...]
    title_selectors: tuple[str, ...]
    price_selectors: tuple[str, ...]
    mileage_selectors: tuple[str, ...] = ()
    location_selectors: tuple[str, ...] = ()
    max_pages: int = 5
    # If True, parse __NEXT_DATA__ JSON instead of DOM.
    use_next_data: bool = False
    next_data_path: tuple[str, ...] = ()


def _first_text(card, selectors: Iterable[str]) -> str | None:
    for sel in selectors:
        n = card.css_first(sel)
        if n:
            t = n.text(strip=True)
            if t:
                return t
    return None


def _first_node(card, selectors: Iterable[str]):
    for sel in selectors:
        n = card.css_first(sel)
        if n:
            return n
    return None


def _next_data_listings(html: str, path: tuple[str, ...]) -> list[dict]:
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")
    if not node:
        return []
    try:
        blob = json.loads(node.text() or "{}")
    except json.JSONDecodeError:
        return []
    cur = blob
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return []
        cur = cur[k]
    return cur if isinstance(cur, list) else []


def _listing_from_card(card, config: SiteConfig) -> Listing | None:
    link = _first_node(card, config.title_selectors)
    if not link:
        return None
    href = link.attributes.get("href")
    if not href:
        return None
    url = urljoin(config.base, href)
    title = link.text(strip=True) or link.attributes.get("title") or ""
    price = parse_price(_first_text(card, config.price_selectors))
    miles = parse_miles(_first_text(card, config.mileage_selectors))
    loc = _first_text(card, config.location_selectors)
    img = card.css_first("img")
    listing = Listing(
        source=config.slug,
        source_url=url,
        title=title,
        year=parse_year(title),
        current_bid_usd=price,
        mileage=miles,
        location=loc,
        photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
        title_status=infer_title_status(title),
        seller_type="auction",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


def _listing_from_next_data(d: dict, config: SiteConfig) -> Listing | None:
    title = d.get("title") or d.get("name") or " ".join(filter(None, [str(d.get("year") or ""), d.get("make") or "", d.get("model") or ""]))
    slug = d.get("slug") or d.get("url") or d.get("permalink")
    if not slug:
        return None
    url = slug if slug.startswith("http") else urljoin(config.base, slug)
    listing = Listing(
        source=config.slug,
        source_url=url,
        title=title,
        year=d.get("year") or parse_year(title),
        current_bid_usd=parse_price(d.get("currentBid") or d.get("price")),
        mileage=parse_miles(d.get("mileage") or d.get("odometer")),
        location=d.get("location") or d.get("sellerLocation"),
        photo_url=((d.get("images") or [{}])[0].get("url")
                   if isinstance(d.get("images"), list) and d.get("images")
                   else d.get("image")),
        title_status=infer_title_status(title),
        seller_type="auction",
        raw={"raw": d},
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


def parse_results(html: str, config: SiteConfig) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    if config.use_next_data:
        for d in _next_data_listings(html, config.next_data_path):
            listing = _listing_from_next_data(d, config)
            if listing and listing.source_url not in seen:
                seen.add(listing.source_url)
                out.append(listing)
        if out:
            return out
    tree = HTMLParser(html)
    for sel in config.card_selectors:
        cards = tree.css(sel)
        if cards:
            break
    else:
        cards = []
    for card in cards:
        listing = _listing_from_card(card, config)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


CONFIGS: dict[str, SiteConfig] = {
    "hagerty_marketplace": SiteConfig(
        slug="hagerty_marketplace",
        name="Hagerty Marketplace",
        base="https://www.hagerty.com",
        search_url_template=(
            "https://www.hagerty.com/marketplace/search"
            "?type=auctions&make=Porsche&forSale=true&page={page}"
        ),
        card_selectors=("[data-testid='auction-card']", ".auction-card", "article[class*='card']"),
        title_selectors=("a[href*='/marketplace/auction/']", "h2 a", "h3 a"),
        price_selectors=("[data-testid='current-bid']", ".price", ".current-bid"),
        mileage_selectors=("[data-testid='mileage']", ".mileage"),
        location_selectors=("[data-testid='location']", ".location"),
        use_next_data=True,
        next_data_path=("props", "pageProps", "results"),
    ),
    "collecting_cars": SiteConfig(
        slug="collecting_cars",
        name="Collecting Cars",
        base="https://collectingcars.com",
        search_url_template=(
            "https://collectingcars.com/for-sale/porsche?page={page}&currency=USD"
        ),
        card_selectors=(".auction-card", "[data-testid='auction-card']", "article.lot"),
        title_selectors=("a.auction-card__title", "a[href*='/for-sale/']", "h3 a"),
        price_selectors=(".auction-card__bid", ".current-bid", ".price"),
        mileage_selectors=(".auction-card__mileage", ".mileage"),
        location_selectors=(".auction-card__location", ".location"),
    ),
    "themarket": SiteConfig(
        # themarket.bonhams.com migrated to themarket.co.uk in 2025.
        slug="themarket",
        name="The Market by Bonhams",
        base="https://themarket.co.uk",
        search_url_template=(
            "https://themarket.co.uk/cars-for-sale/?make=porsche&page={page}"
        ),
        card_selectors=("article.car-card", ".search-result-card", ".lot-card"),
        title_selectors=(".car-card__title a", "h3 a", "a[href*='/car/']"),
        price_selectors=(".car-card__price", ".price", ".current-bid"),
        mileage_selectors=(".car-card__mileage", ".mileage"),
        location_selectors=(".car-card__location", ".location"),
    ),
    "autohunter": SiteConfig(
        slug="autohunter",
        name="AutoHunter",
        base="https://www.autohunter.com",
        search_url_template=(
            "https://www.autohunter.com/vehicle-listings/"
            "?make=Porsche&status=live&year_min={year_min}&price_max={price_max}&page={page}"
        ),
        card_selectors=(".listing-card", ".auction-card", "article.lot"),
        title_selectors=(".listing-card__title a", "h3 a", "a[href*='/auction/']"),
        price_selectors=(".listing-card__price", ".current-bid", ".price"),
        mileage_selectors=(".listing-card__mileage",),
        location_selectors=(".listing-card__location",),
    ),
    "broad_arrow": SiteConfig(
        slug="broad_arrow",
        name="Broad Arrow",
        base="https://broadarrowauctions.com",
        # No site-wide make filter — we crawl the listings index and filter
        # client-side via the title.
        search_url_template="https://broadarrowauctions.com/auctions?page={page}",
        card_selectors=(".lot-card", ".auction-lot", "article.lot"),
        title_selectors=(".lot-card__title a", "h3 a", "a[href*='/lots/']"),
        price_selectors=(".lot-card__estimate", ".estimate", ".price"),
    ),
    "iconic_auctioneers": SiteConfig(
        # Silverstone Auctions rebranded to Iconic Auctioneers.
        slug="iconic_auctioneers",
        name="Iconic Auctioneers",
        base="https://www.iconicauctioneers.com",
        search_url_template=(
            "https://www.iconicauctioneers.com/auctions?make=porsche&page={page}"
        ),
        card_selectors=(".lot-card", ".auction-lot", ".car-card"),
        title_selectors=(".lot-card__title a", "h3 a", "a[href*='/lot/']"),
        price_selectors=(".lot-card__estimate", ".estimate", ".price"),
    ),
}


class EnthusiastAuctionScraper(BaseScraper):
    timeout_s = 240.0

    def __init__(self, config: SiteConfig, *, year_min: int = 2014, price_max: int = 45_000):
        self.config = config
        self.slug = config.slug
        self.name = config.name
        self.year_min = year_min
        self.price_max = price_max

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            url = self.config.search_url_template.format(
                year_min=self.year_min, price_max=self.price_max, page=page
            )
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s page %d: %s", self.slug, page, exc)
                break
            listings = parse_results(html, self.config)
            fresh = [l for l in listings if l.source_url not in seen]
            if not fresh:
                break
            seen.update(l.source_url for l in fresh)
            out.extend(fresh)
        return out


def make_hagerty(year_min=2014, price_max=45000):
    return EnthusiastAuctionScraper(CONFIGS["hagerty_marketplace"], year_min=year_min, price_max=price_max)


def make_collecting_cars(year_min=2014, price_max=45000):
    return EnthusiastAuctionScraper(CONFIGS["collecting_cars"], year_min=year_min, price_max=price_max)


def make_themarket(year_min=2014, price_max=45000):
    return EnthusiastAuctionScraper(CONFIGS["themarket"], year_min=year_min, price_max=price_max)


def make_autohunter(year_min=2014, price_max=45000):
    return EnthusiastAuctionScraper(CONFIGS["autohunter"], year_min=year_min, price_max=price_max)


def make_broad_arrow(year_min=2014, price_max=45000):
    return EnthusiastAuctionScraper(CONFIGS["broad_arrow"], year_min=year_min, price_max=price_max)


def make_iconic(year_min=2014, price_max=45000):
    return EnthusiastAuctionScraper(CONFIGS["iconic_auctioneers"], year_min=year_min, price_max=price_max)
