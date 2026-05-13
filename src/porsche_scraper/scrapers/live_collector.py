"""Live collector auction houses — Mecum, Barrett-Jackson, RM Sotheby's,
Gooding, Bonhams Cars.

These are major in-person events with online preview/bid. They list
upcoming consignments well in advance; "sold" status appears post-sale.
Estimates (low/high range) are usually visible on the card; actual hammer
price only on completed lots.

All sit behind DataDome / Cloudflare / Imperva — needs `PROXY_URL` to be
consistently reliable.
"""
from __future__ import annotations

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

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HouseConfig:
    slug: str
    name: str
    base: str
    search_url_template: str
    card_selectors: tuple[str, ...]
    title_selectors: tuple[str, ...]
    estimate_selectors: tuple[str, ...]
    location_selectors: tuple[str, ...] = ()
    max_pages: int = 5


CONFIGS: dict[str, HouseConfig] = {
    "mecum": HouseConfig(
        slug="mecum",
        name="Mecum",
        base="https://www.mecum.com",
        search_url_template="https://www.mecum.com/lots/?Make=Porsche&Page={page}",
        card_selectors=(".lot-card", "article.lot", "div[class*='lot-card']"),
        title_selectors=(".lot-title", "h3 a", "a[href*='/lots/']"),
        estimate_selectors=(".lot-estimate", ".estimate", ".lot-price"),
        location_selectors=(".lot-event", ".lot-location"),
    ),
    "barrett_jackson": HouseConfig(
        slug="barrett_jackson",
        name="Barrett-Jackson",
        base="https://www.barrett-jackson.com",
        search_url_template="https://www.barrett-jackson.com/Search/?Make=Porsche&page={page}",
        card_selectors=(".lot-thumb", ".lot-card", "article.lot"),
        title_selectors=(".lot-info a", ".lot-title a", "h3 a"),
        estimate_selectors=(".lot-price", ".estimate"),
        location_selectors=(".lot-event",),
    ),
    "rm_sothebys": HouseConfig(
        slug="rm_sothebys",
        name="RM Sotheby's",
        base="https://rmsothebys.com",
        search_url_template="https://rmsothebys.com/search?query=porsche&type=lot&page={page}",
        card_selectors=(".lot-tile", "article.lot", "[data-testid='lot-card']"),
        title_selectors=(".lot-title a", "h3 a", "a[href*='/lots/']"),
        estimate_selectors=(".lot-estimate", ".estimate"),
        location_selectors=(".lot-location", ".lot-event"),
    ),
    "gooding": HouseConfig(
        slug="gooding",
        name="Gooding & Company",
        base="https://www.goodingco.com",
        search_url_template="https://www.goodingco.com/inventory/?make=Porsche&page={page}",
        card_selectors=(".lot-listing", "article.lot", ".inventory-item"),
        title_selectors=(".lot-title a", "h3 a", "a[href*='/lots/']"),
        estimate_selectors=(".estimate", ".lot-estimate"),
    ),
    "bonhams_cars": HouseConfig(
        slug="bonhams_cars",
        name="Bonhams Cars",
        base="https://cars.bonhams.com",
        search_url_template=(
            "https://cars.bonhams.com/auctions/upcoming/?make=Porsche&page={page}"
        ),
        card_selectors=(".lot-summary", "article.lot", ".search-result"),
        title_selectors=(".lot-title a", "h3 a", "a[href*='/lot/']"),
        estimate_selectors=(".lot-estimate-low", ".lot-estimate", ".estimate"),
        location_selectors=(".lot-location", ".lot-event"),
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


def parse_results(html: str, config: HouseConfig) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    cards = []
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
        if url in seen:
            continue
        seen.add(url)
        title = link.text(strip=True)
        if "porsche" not in title.lower():
            continue  # No make filter on some endpoints — drop non-Porsches.
        est = _first_text(card, config.estimate_selectors)
        # Estimates are usually "$30,000 - $45,000"; we take the low end as the bid signal.
        est_low = parse_price(est.split("-")[0]) if est else None
        img = card.css_first("img")
        listing = Listing(
            source=config.slug,
            source_url=url,
            title=title,
            year=parse_year(title),
            current_bid_usd=est_low,
            location=_first_text(card, config.location_selectors),
            photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
            title_status=infer_title_status(title),
            seller_type="auction",
            raw={"estimate_str": est},
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


class LiveCollectorScraper(BaseScraper):
    timeout_s = 240.0

    def __init__(self, config: HouseConfig):
        self.config = config
        self.slug = config.slug
        self.name = config.name

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            url = self.config.search_url_template.format(page=page)
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


def make_mecum():
    return LiveCollectorScraper(CONFIGS["mecum"])


def make_barrett_jackson():
    return LiveCollectorScraper(CONFIGS["barrett_jackson"])


def make_rm_sothebys():
    return LiveCollectorScraper(CONFIGS["rm_sothebys"])


def make_gooding():
    return LiveCollectorScraper(CONFIGS["gooding"])


def make_bonhams_cars():
    return LiveCollectorScraper(CONFIGS["bonhams_cars"])
