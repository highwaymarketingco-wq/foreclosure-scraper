"""Salvage-auction brokers — Copart/IAA proxies for non-dealers.

These five sites all front the same Copart + IAA inventory but let
individuals bid via a broker (for a per-transaction fee). The HTML
templates are very similar — `.car-item` / `.lot-card` style grids with
year/model/price/odometer/title-status spans. We share one parser
config-driven across all five.

Sites covered:
- sca.auction         (en.sca.auction)
- autobidmaster.com
- abetter.bid         (formerly abetterbid.com — 301)
- cars4.bid           (thin mirror of abetter.bid)
- auctionexport.com

All sit behind Cloudflare — uses the stealth (curl-cffi) transport. Set
PROXY_URL to a residential proxy for reliable use at scale.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_rendered, fetch_text_stealth
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
    search_url: str  # Format string with {price_max} and {year_min}
    card_selectors: tuple[str, ...]
    title_selectors: tuple[str, ...]
    price_selectors: tuple[str, ...]
    mileage_selectors: tuple[str, ...]
    location_selectors: tuple[str, ...]
    title_status_selectors: tuple[str, ...]
    max_pages: int = 5
    pagination_param: str = "page"


CONFIGS: dict[str, SiteConfig] = {
    "sca_auction": SiteConfig(
        slug="sca_auction",
        name="SCA Auction",
        base="https://en.sca.auction",
        search_url=(
            "https://en.sca.auction/cars?make=Porsche"
            "&yearFrom={year_min}&priceTo={price_max}&page={page}"
        ),
        card_selectors=(".lot-card", "div[class*='lot-card']"),
        title_selectors=(".lot-card__title a", ".lot-title a", "h3 a"),
        price_selectors=(".lot-card__price", ".price-value", ".price"),
        mileage_selectors=(".lot-card__odometer", ".odo-value", ".odometer"),
        location_selectors=(".lot-card__location", ".location-value"),
        title_status_selectors=(".lot-card__damage", ".lot-card__title-doc", ".title-doc"),
    ),
    "autobidmaster": SiteConfig(
        slug="autobidmaster",
        name="AutoBidMaster",
        base="https://www.autobidmaster.com",
        search_url=(
            "https://www.autobidmaster.com/en/carfinder-online-auto-auctions/Porsche/"
            "?price_to={price_max}&year_from={year_min}&page={page}"
        ),
        card_selectors=(".lot-list-item", ".car-item-block", "div[class*='lot-item']"),
        title_selectors=(".car-name a", ".lot-title a", "a[href*='/lot/']"),
        price_selectors=(".car-price .price-value", ".price-value", ".lot-price"),
        mileage_selectors=(".lot-info-odometer", ".odometer-value"),
        location_selectors=(".lot-info-location", ".location"),
        title_status_selectors=(".lot-info-title-doc", ".title-doc"),
    ),
    "abetter_bid": SiteConfig(
        # Verified 2026-05-14: real URL is /en/car-finder/type-automobiles/
        # make-porsche; the old /cars/porsche/ 404s. Card class is
        # .car-card; title is .car-card__header-title; URL format
        # /en/{LOT_NUMBER}-{year}-porsche-{model}.
        # Selectolax doesn't support CSS4 :has() / :contains(), so we
        # match details by class only — the parser elsewhere extracts
        # specific fields with text regex on the matched node.
        slug="abetter_bid",
        name="A Better Bid",
        base="https://abetter.bid",
        search_url=(
            "https://abetter.bid/en/car-finder/type-automobiles/make-porsche"
        ),
        card_selectors=(".car-card",),
        title_selectors=(".car-card__header-title",),
        price_selectors=(".car-card__price",),
        mileage_selectors=(".car-card__details-text",),
        location_selectors=(".car-card__details-text",),
        title_status_selectors=(".car-card__details-text",),
        max_pages=2,
    ),
    "cars4_bid": SiteConfig(
        # Verified 2026-05-14: real URL is /cars-for-sale/porsche-manufacturer/.
        # Lot URLs: /vehicle/{iaai|copart}-{LOT_NUMBER}-{title}-{year}-porsche-{model}
        # The card structure is bootstrap-ish ms-1 wrappers — title link
        # is what we anchor on.
        slug="cars4_bid",
        name="Cars4.bid",
        base="https://cars4.bid",
        search_url=(
            "https://cars4.bid/cars-for-sale/porsche-manufacturer/"
        ),
        card_selectors=(".ms-1",),
        title_selectors=("a[href*='/vehicle/']",),
        price_selectors=(".price",),
        mileage_selectors=(".odometer",),
        location_selectors=(".location",),
        title_status_selectors=(".title-status",),
        max_pages=2,
    ),
    "auctionexport": SiteConfig(
        slug="auctionexport",
        name="AuctionExport",
        base="https://www.auctionexport.com",
        search_url=(
            "https://www.auctionexport.com/en/Inventory/Search"
            "?Make=Porsche&YearFrom={year_min}&PriceTo={price_max}&page={page}"
        ),
        card_selectors=(".inv-cars-block", "tr.row-inv", "div[class*='car-item']"),
        title_selectors=(".car-title a", "a[href*='/Inventory/']", "h4 a"),
        price_selectors=(".price-value", ".car-price"),
        mileage_selectors=(".odo-value", ".odometer"),
        location_selectors=(".location-value", ".location"),
        title_status_selectors=(".title-status", ".damage", ".title-doc"),
    ),
}


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


# Many salvage brokers leak the underlying lot number in the URL —
# capturing it lets us dedupe across SCA/AutoBidMaster/ABetter.bid when
# they relist the same Copart car. Patterns we've seen in the wild
# (verified 2026-05-14):
#   abetter.bid:    /en/{LOT}-{year}-porsche-{model}        (10-digit leading)
#   cars4.bid:      /vehicle/(iaai|copart)-{LOT}-{...}      (8-digit)
#   autobidmaster:  /en/search/lot/{LOT}/copart-{...}
#   sca/old style:  /lot/{LOT}/...  /cars/{...}-{LOT}
_LOT_NUM_PATTERNS = (
    re.compile(r"/(?:search/lot|lot|cars?|inventory)/[^?#]*?(\d{6,12})", re.IGNORECASE),
    re.compile(r"/vehicle/(?:iaai|copart)-(\d{6,12})", re.IGNORECASE),
    re.compile(r"/en/(\d{8,12})-\d{4}-porsche", re.IGNORECASE),
)


def _extract_lot_id(url: str) -> str | None:
    for pat in _LOT_NUM_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def parse_results_html(html: str, config: SiteConfig) -> list[Listing]:
    """Parse one search-results page using a per-site SiteConfig."""
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    cards: list = []
    for sel in config.card_selectors:
        cards = tree.css(sel)
        if cards:
            break
    for card in cards:
        link = _first_node(card, config.title_selectors)
        if not link:
            continue
        href = link.attributes.get("href")
        if not href:
            continue
        url = urljoin(config.base, href)
        title = link.text(strip=True) or link.attributes.get("title") or ""
        price = parse_price(_first_text(card, config.price_selectors))
        miles = parse_miles(_first_text(card, config.mileage_selectors))
        loc = _first_text(card, config.location_selectors)
        status_text = _first_text(card, config.title_status_selectors) or title
        img_node = card.css_first("img")
        img = (img_node.attributes.get("src") or img_node.attributes.get("data-src")) if img_node else None
        lot_id = _extract_lot_id(url)
        status = infer_title_status(status_text)
        listing = Listing(
            source=config.slug,
            source_url=url,
            listing_id=lot_id,
            lot_number=lot_id,  # cross-source dedupe — same physical Copart/IAA lot
            title=title,
            year=parse_year(title),
            current_bid_usd=price,
            mileage=miles,
            location=loc,
            photo_url=img,
            title_status=status,
            seller_type="salvage_auction",
        )
        listing.drivable = infer_drivable(title, status)
        if url in seen:
            continue
        seen.add(url)
        out.append(listing)
    return out


class SalvageBrokerScraper(BaseScraper):
    """Generic salvage-broker scraper driven by a SiteConfig."""

    timeout_s = 240.0

    def __init__(self, config: SiteConfig, *, year_min: int = 2014, price_max: int = 45_000):
        self.config = config
        self.slug = config.slug
        self.name = config.name
        self.year_min = year_min
        self.price_max = price_max

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            url = self.config.search_url.format(
                year_min=self.year_min, price_max=self.price_max, page=page
            )
            try:
                # Salvage-broker sites are all Cloudflare/JS-fronted apps
                # (verified 2026-05-14: abetter.bid 404s on plain curl,
                # cars4.bid 403s, autobidmaster returns a 1KB JS shell).
                # Skip curl-cffi entirely and go straight to a rendered
                # fetch. Chaining curl_cffi -> Scrapling in the same
                # process has produced segfaults — render is the only
                # safe primary path here.
                html = await fetch_rendered(
                    url, timeout=90,
                    wait_for_selector=None,  # let network_idle handle it
                    scroll_iterations=3,
                    post_scroll_wait_ms=2500,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("%s page %d failed: %s", self.slug, page, exc)
                break
            listings = parse_results_html(html, self.config)
            # When the search URL doesn't actually paginate (e.g. abetter.bid's
            # /en/car-finder/... ignores ?page=N), the same lots come back
            # every iteration — dedupe by source_url across pages so we
            # don't return 3× copies.
            new_count = 0
            for li in listings:
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                out.append(li)
                new_count += 1
            if new_count == 0:
                break
        return out


def make_sca_auction(year_min=2014, price_max=45000):
    return SalvageBrokerScraper(CONFIGS["sca_auction"], year_min=year_min, price_max=price_max)


def make_autobidmaster(year_min=2014, price_max=45000):
    return SalvageBrokerScraper(CONFIGS["autobidmaster"], year_min=year_min, price_max=price_max)


def make_abetter_bid(year_min=2014, price_max=45000):
    return SalvageBrokerScraper(CONFIGS["abetter_bid"], year_min=year_min, price_max=price_max)


def make_cars4_bid(year_min=2014, price_max=45000):
    return SalvageBrokerScraper(CONFIGS["cars4_bid"], year_min=year_min, price_max=price_max)


def make_auctionexport(year_min=2014, price_max=45000):
    return SalvageBrokerScraper(CONFIGS["auctionexport"], year_min=year_min, price_max=price_max)
