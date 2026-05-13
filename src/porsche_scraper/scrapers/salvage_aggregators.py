"""Salvage / damaged Porsche aggregators that proxy Copart + IAA data.

Copart and IAA themselves are hard to scrape (heavy bot defences, dealer-
auth gates on many endpoints). A small ecosystem of broker / aggregator
sites mirrors their inventory with friendlier markup. They make money on
referral fees and so don't try as hard to block scrapers.

This module adds:

- bid_cars      — bid.cars Copart/IAA aggregator (HTML, /vehicles/porsche/)
- carfast       — carfast.express, same idea
- autoauctionspy — autoauctionspy.com, Copart-focused
- cargurus_salvage — cargurus.com with rebuilt/salvage filter
- ebay_salvage  — ebay Motors with LH_TitleType=1 (rebuilt+salvage) filter

All share one generic config-driven base because the markup is similar
across them.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_text, fetch_text_stealth
from ..models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AggregatorConfig:
    slug: str
    name: str
    base: str
    search_url_template: str   # accepts {page}
    card_selectors: tuple[str, ...]
    title_selectors: tuple[str, ...]
    price_selectors: tuple[str, ...]
    mileage_selectors: tuple[str, ...] = ()
    location_selectors: tuple[str, ...] = ()
    title_status_selectors: tuple[str, ...] = ()
    max_pages: int = 5
    use_stealth: bool = True
    # When the source is a Copart/IAA mirror we know the listings are
    # salvage; override the inferred title status accordingly.
    default_title_status: TitleStatus | None = None
    seller_type: str = "salvage_auction"


CONFIGS: dict[str, AggregatorConfig] = {
    "bid_cars": AggregatorConfig(
        slug="bid_cars",
        name="Bid.cars (Copart/IAA aggregator)",
        base="https://bid.cars",
        # Bid.cars lists every Copart/IAA Porsche under /search/results/?make=PORSCHE
        search_url_template=(
            "https://bid.cars/search/results/?make=PORSCHE&page={page}"
        ),
        card_selectors=(".lot-list-item", ".car-card", "div[class*='lot']", "tr.lot"),
        title_selectors=(".lot-title a", "a[href*='/lot/']", "h3 a"),
        price_selectors=(".lot-price", ".price", ".final-bid"),
        mileage_selectors=(".lot-odo", ".odometer"),
        location_selectors=(".lot-location", ".location"),
        title_status_selectors=(".title-doc", ".title-type", ".title-status"),
        default_title_status=TitleStatus.SALVAGE,
    ),
    "carfast": AggregatorConfig(
        slug="carfast",
        name="Carfast.express (Copart/IAA aggregator)",
        base="https://carfast.express",
        search_url_template=(
            "https://carfast.express/auctions/copart-iaa/porsche?page={page}"
        ),
        card_selectors=(".vehicle-card", ".lot-card", "article.car"),
        title_selectors=(".vehicle-title a", "a[href*='/auction/']", "h3 a"),
        price_selectors=(".price-value", ".current-bid", ".price"),
        mileage_selectors=(".odometer", ".mileage"),
        location_selectors=(".location",),
        title_status_selectors=(".title-doc",),
        default_title_status=TitleStatus.SALVAGE,
    ),
    "autoauctionspy": AggregatorConfig(
        slug="autoauctionspy",
        name="AutoAuctionSpy (Copart aggregator)",
        base="https://autoauctionspy.com",
        search_url_template=(
            "https://autoauctionspy.com/copart-iaai/lots/?make=Porsche&page={page}"
        ),
        card_selectors=(".lot-item", ".result-row", "article"),
        title_selectors=(".lot-info a", "a[href*='/lot/']"),
        price_selectors=(".lot-price",),
        mileage_selectors=(".odo",),
        location_selectors=(".yard", ".location"),
        title_status_selectors=(".title-doc", ".title-type"),
        default_title_status=TitleStatus.SALVAGE,
    ),
    "cargurus_salvage": AggregatorConfig(
        slug="cargurus_salvage",
        name="CarGurus (salvage/rebuilt filter)",
        base="https://www.cargurus.com",
        # CarGurus supports a "titleTypes" filter:
        #   SALVAGE_TITLE | REBUILT_TITLE | LEMON_TITLE | FLOOD_TITLE
        search_url_template=(
            "https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
            "?sourceContext=carGurusHomePageModel"
            "&entitySelectingHelper.selectedEntity=m37"  # Porsche make
            "&minYear=2014"
            "&titleTypes=SALVAGE_TITLE,REBUILT_TITLE,LEMON_TITLE,FLOOD_TITLE"
            "&page={page}"
        ),
        card_selectors=(".cg-dealFinder-result-wrap", "[data-cg-ft='car-blade']", "article"),
        title_selectors=(".cg-dealFinder-result-model", "h4 a", "a[href*='/Cars/inventorylisting/']"),
        price_selectors=(".cg-dealFinder-result-price", ".car-price"),
        mileage_selectors=(".car-mileage", "[data-cg-ft='mileage']"),
        location_selectors=(".car-loc", "[data-cg-ft='location']"),
        title_status_selectors=(".title-type",),
        # CarGurus tags each car with its title type; let the inferred
        # status from the badge stand (rebuilt/salvage/lemon/flood).
    ),
    "ebay_salvage": AggregatorConfig(
        slug="ebay_salvage",
        name="eBay Motors (salvage/rebuilt title)",
        base="https://www.ebay.com",
        # LH_TitleType=1 = rebuilt/salvage; categoryId 6001 = cars.
        search_url_template=(
            "https://www.ebay.com/sch/Cars-Trucks/6001/i.html"
            "?_nkw=porsche&_ipg=200&_pgn={page}"
            "&LH_TitleType=1"  # rebuilt/salvage filter
        ),
        card_selectors=("li.s-item",),
        title_selectors=(".s-item__title", "a.s-item__link"),
        price_selectors=(".s-item__price",),
        location_selectors=(".s-item__location",),
        title_status_selectors=(".s-item__subtitle",),
        use_stealth=False,  # eBay plain httpx usually OK, 503 if rate-limited
        seller_type="dealer",
    ),
}


def _first_text(card, selectors):
    for sel in selectors:
        n = card.css_first(sel)
        if n and n.text(strip=True):
            return n.text(strip=True)
    return None


def _first_node(card, selectors):
    for sel in selectors:
        n = card.css_first(sel)
        if n:
            return n
    return None


def parse_results(html: str, config: AggregatorConfig) -> list[Listing]:
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
        url = href if href.startswith("http") else urljoin(config.base, href)
        if url in seen:
            continue
        seen.add(url)
        title = link.text(strip=True) or link.attributes.get("title") or ""
        if title.lower().startswith("shop on ebay"):
            continue  # eBay promo row
        if "porsche" not in title.lower():
            continue
        # Excluded models — drop server-side before producing a listing.
        if any(em in title.lower() for em in ("panamera", "cayenne", "macan")):
            continue
        img_node = card.css_first("img")
        img = (img_node.attributes.get("src") or img_node.attributes.get("data-src")) if img_node else None
        status_text = _first_text(card, config.title_status_selectors) or title
        status = infer_title_status(status_text)
        if status == TitleStatus.UNKNOWN and config.default_title_status:
            status = config.default_title_status
        listing = Listing(
            source=config.slug,
            source_url=url,
            listing_id=url.rstrip("/").rsplit("/", 1)[-1],
            title=title,
            year=parse_year(title),
            price_usd=parse_price(_first_text(card, config.price_selectors)),
            mileage=parse_miles(_first_text(card, config.mileage_selectors)),
            location=_first_text(card, config.location_selectors),
            photo_url=img,
            title_status=status,
            seller_type=config.seller_type,
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


class _AggregatorScraper(BaseScraper):
    timeout_s = 240.0

    def __init__(self, config: AggregatorConfig):
        self.config = config
        self.slug = config.slug
        self.name = config.name

    async def fetch(self) -> list[Listing]:
        fetcher = fetch_text_stealth if self.config.use_stealth else fetch_text
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            url = self.config.search_url_template.format(page=page)
            try:
                html = await fetcher(url, timeout=45)
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


def make_bid_cars():
    return _AggregatorScraper(CONFIGS["bid_cars"])


def make_carfast():
    return _AggregatorScraper(CONFIGS["carfast"])


def make_autoauctionspy():
    return _AggregatorScraper(CONFIGS["autoauctionspy"])


def make_cargurus_salvage():
    return _AggregatorScraper(CONFIGS["cargurus_salvage"])


def make_ebay_salvage():
    return _AggregatorScraper(CONFIGS["ebay_salvage"])
