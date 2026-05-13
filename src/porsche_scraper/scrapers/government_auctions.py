"""Government / seized-asset auctions.

GovDeals, GSA Auctions, US Marshals (CWS Marketing), PublicSurplus,
PropertyRoom, Municibid.

GSA has the cleanest path — a public JSON API. The rest are HTML.
PropertyRoom often shows car listings only behind a login; included
anyway since the *list* page is public and gives at least make/year.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_json, fetch_rendered, fetch_text, fetch_text_stealth
from ..models import (
    Listing,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)


# ---------- GSA Auctions (JSON API) ----------


class GsaAuctionsScraper(BaseScraper):
    slug = "gsa_auctions"
    name = "GSA Auctions"
    BASE = "https://gsaauctions.gov"

    def __init__(self, *, max_pages: int = 5):
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        # Try the JSON API first; if the path 404s, fall back to rendered HTML.
        api_ok = True
        for page in range(1, self.max_pages + 1):
            if api_ok:
                url = (
                    f"{self.BASE}/api/v1/listings?"
                    f"{urlencode({'keyword': 'porsche', 'category': 'Vehicles', 'page': page})}"
                )
                try:
                    data = await fetch_json(
                        url, timeout=30, headers={"Accept": "application/json"}
                    )
                    items = data.get("listings") or data.get("results") or data.get("data") or []
                    if items:
                        for d in items:
                            listing = self._listing(d)
                            if listing:
                                out.append(listing)
                        continue
                    if page == 1:
                        api_ok = False  # API exists but empty — try HTML.
                    else:
                        break
                except Exception as exc:  # noqa: BLE001
                    log.info("gsa_auctions API page %d failed: %s — trying HTML", page, exc)
                    api_ok = False
            if not api_ok:
                url = f"{self.BASE}/auctions/search?keyword=porsche&page={page}"
                try:
                    html = await fetch_rendered(
                        url, timeout=90,
                        wait_for_selector="a[href*='/listing/'], .listing-card",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("gsa_auctions HTML page %d: %s", page, exc)
                    break
                tree = HTMLParser(html)
                cards = tree.css(".listing-card, a[href*='/listing/']")
                if not cards:
                    break
                for c in cards:
                    a = c.css_first("a") if c.tag != "a" else c
                    if not a:
                        continue
                    href = a.attributes.get("href") or ""
                    if not href:
                        continue
                    title = a.text(strip=True)
                    if "porsche" not in title.lower():
                        continue
                    out.append(self._listing_from_html(title, href))
        return out

    def _listing_from_html(self, title: str, href: str) -> Listing:
        listing = Listing(
            source=self.slug,
            source_url=urljoin(self.BASE, href),
            title=title,
            year=parse_year(title),
            title_status=infer_title_status(title),
            seller_type="government",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        return listing

    def _listing(self, d: dict) -> Listing | None:
        title = d.get("title") or d.get("name") or ""
        slug = d.get("url") or f"/listing/{d.get('id')}"
        listing = Listing(
            source=self.slug,
            source_url=urljoin(self.BASE, slug),
            listing_id=str(d.get("id") or ""),
            title=title,
            year=parse_year(title),
            current_bid_usd=parse_price(d.get("currentBid") or d.get("current_bid")),
            price_usd=parse_price(d.get("buyNowPrice")),
            mileage=parse_miles(d.get("mileage") or d.get("odometer")),
            location=d.get("location"),
            photo_url=d.get("image") or d.get("thumbnail"),
            title_status=infer_title_status(title),
            seller_type="government",
            raw={"gsa": d},
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        return listing


# ---------- Generic HTML gov-auction sites ----------


@dataclass(frozen=True)
class GovSiteConfig:
    slug: str
    name: str
    base: str
    search_url_template: str
    card_selectors: tuple[str, ...]
    title_selectors: tuple[str, ...]
    price_selectors: tuple[str, ...]
    location_selectors: tuple[str, ...] = ()
    use_stealth: bool = False
    # If True the page is a JS-rendered SPA — go straight to Scrapling.
    use_render: bool = False
    # Optional selector to wait for after the page loads (Scrapling only).
    render_wait_selector: str | None = None
    max_pages: int = 5


CONFIGS: dict[str, GovSiteConfig] = {
    "govdeals": GovSiteConfig(
        slug="govdeals",
        name="GovDeals",
        base="https://www.govdeals.com",
        # GovDeals is now an Angular SPA — search?keyword=… replaces the legacy index.cfm path.
        search_url_template=(
            "https://www.govdeals.com/search?keyword=porsche&category=Vehicles&page={page}"
        ),
        card_selectors=(
            "div[data-testid='asset-card']", ".asset-card", "div.asset",
            "tr.assetSearchResult", "div[class*='asset']",
        ),
        title_selectors=(
            "a[data-testid='asset-title']", "a.asset-title", "a[href*='/asset/']", "h3 a",
        ),
        price_selectors=(".current-bid", "[data-testid='current-bid']", ".bid-amount", ".price"),
        location_selectors=(".location", "[data-testid='location']"),
        use_render=True,
        render_wait_selector="a[href*='/asset/'], .asset-card, [data-testid='asset-card']",
    ),
    "public_surplus": GovSiteConfig(
        slug="public_surplus",
        name="Public Surplus",
        base="https://www.publicsurplus.com",
        search_url_template=(
            "https://www.publicsurplus.com/sms/browse/search"
            "?keyword=porsche&catId=8&page={page}"
        ),
        card_selectors=(
            "table.list-auction tr", ".auction-row", "tr[class*='auction']",
            "div.auction-listing",
        ),
        title_selectors=("a.auction-title", "a[href*='/auction']", "h3 a"),
        price_selectors=(".amount", ".current-bid"),
        location_selectors=(".location",),
        use_render=True,
        render_wait_selector="a[href*='/auction'], .auction-row",
    ),
    "property_room": GovSiteConfig(
        slug="property_room",
        name="PropertyRoom",
        base="https://www.propertyroom.com",
        search_url_template=(
            "https://www.propertyroom.com/search?"
            "searchTerm=porsche&category=vehicles&page={page}"
        ),
        card_selectors=(".auction-item-card", ".search-result", "article.lot"),
        title_selectors=(".item-title a", "h3 a", "a[href*='/listing/']"),
        price_selectors=(".bid-amount", ".current-bid"),
        location_selectors=(".location",),
        use_stealth=True,
    ),
    "municibid": GovSiteConfig(
        slug="municibid",
        name="Municibid",
        base="https://www.municibid.com",
        search_url_template=(
            "https://www.municibid.com/search?q=porsche&page={page}"
        ),
        card_selectors=(".listing-card", ".auction-card", "article.lot"),
        title_selectors=(".listing-title a", "a[href*='/listings/']"),
        price_selectors=(".current-bid", ".bid-amount"),
        location_selectors=(".location",),
        use_stealth=True,
    ),
    "cws_marketing": GovSiteConfig(
        # US Marshals contracts cwsmarketing.com for seized vehicle sales.
        slug="cws_marketing",
        name="CWS Marketing (US Marshals)",
        base="https://cwsmarketing.com",
        search_url_template="https://cwsmarketing.com/auctions/?search=porsche&page={page}",
        card_selectors=(".auction-item", ".lot", "article.auction"),
        title_selectors=(".lot-info a", "h3 a", "a[href*='/auction/']"),
        price_selectors=(".lot-price", ".bid", ".price"),
        location_selectors=(".lot-location",),
        use_stealth=True,
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


def parse_results(html: str, config: GovSiteConfig) -> list[Listing]:
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
            continue  # Search hits sometimes broad-match.
        img = card.css_first("img")
        listing = Listing(
            source=config.slug,
            source_url=url,
            title=title,
            year=parse_year(title),
            current_bid_usd=parse_price(_first_text(card, config.price_selectors)),
            location=_first_text(card, config.location_selectors),
            photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
            title_status=infer_title_status(title),
            seller_type="government",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


class GovHtmlScraper(BaseScraper):
    timeout_s = 180.0

    def __init__(self, config: GovSiteConfig):
        self.config = config
        self.slug = config.slug
        self.name = config.name

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            url = self.config.search_url_template.format(page=page)
            try:
                if self.config.use_render:
                    html = await fetch_rendered(
                        url, timeout=90,
                        wait_for_selector=self.config.render_wait_selector,
                    )
                elif self.config.use_stealth:
                    html = await fetch_text_stealth(url, timeout=60)
                else:
                    html = await fetch_text(url, timeout=60)
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


def make_govdeals():
    return GovHtmlScraper(CONFIGS["govdeals"])


def make_public_surplus():
    return GovHtmlScraper(CONFIGS["public_surplus"])


def make_property_room():
    return GovHtmlScraper(CONFIGS["property_room"])


def make_municibid():
    return GovHtmlScraper(CONFIGS["municibid"])


def make_cws_marketing():
    return GovHtmlScraper(CONFIGS["cws_marketing"])
