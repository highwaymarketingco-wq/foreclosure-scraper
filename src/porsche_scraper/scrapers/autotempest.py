"""AutoTempest — federated metasearch across cars.com, eBay, Carvana, etc.

Search URL:
    https://www.autotempest.com/results?
        make=porsche
        &maxprice=45000
        &minyear=2014
        &zip=10001&radius=any

AT renders each source's results into separate panes via XHR; the main
HTML contains the initial cards. Each card is a `.result-item` that
links out to the source listing (we keep both the source-deeplink and
treat AutoTempest as the discovery source).
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_rendered, fetch_text
from ..models import (
    Listing,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://www.autotempest.com"


def _card_to_listing(card) -> Listing | None:
    link = card.css_first("a.listing-link") or card.css_first("a[href^='http']")
    if not link:
        return None
    href = link.attributes.get("href")
    if not href:
        return None
    title_node = card.css_first(".result-title") or card.css_first(".title")
    title = title_node.text(strip=True) if title_node else link.text(strip=True)
    price_node = card.css_first(".result-price") or card.css_first(".price")
    miles_node = card.css_first(".result-mileage") or card.css_first(".mileage")
    loc_node = card.css_first(".result-location") or card.css_first(".location")
    img = card.css_first("img")
    listing = Listing(
        source="autotempest",
        source_url=href,
        title=title,
        year=parse_year(title),
        price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
        mileage=parse_miles(miles_node.text(strip=True)) if miles_node else None,
        location=loc_node.text(strip=True) if loc_node else None,
        photo_url=(img.attributes.get("data-src") or img.attributes.get("src")) if img else None,
        title_status=infer_title_status(title),
        seller_type="aggregator",
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def parse_results_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for card in tree.css(".result-item, .listing-card, .result"):
        listing = _card_to_listing(card)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class AutoTempestScraper(BaseScraper):
    slug = "autotempest"
    name = "AutoTempest"

    def __init__(
        self,
        *,
        year_min: int = 2014,
        price_max: int | None = 45000,
        zip_code: str = "10001",
        radius: str = "any",
    ):
        self.year_min = year_min
        self.price_max = price_max
        self.zip_code = zip_code
        self.radius = radius

    async def fetch(self) -> list[Listing]:
        # AutoTempest streams results in via XHR after page load — the bare
        # HTML response is just a shell. Use Scrapling to get the rendered DOM.
        params = {
            "make": "porsche",
            "minyear": self.year_min,
            "zip": self.zip_code,
            "radius": self.radius,
        }
        if self.price_max is not None:
            params["maxprice"] = self.price_max
        url = f"{BASE}/results?{urlencode(params)}"
        try:
            html = await fetch_rendered(
                url, timeout=90,
                wait_for_selector=".result-item, .listing-card, [class*='result']",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("autotempest failed: %s", exc)
            return []
        return parse_results_html(html)
