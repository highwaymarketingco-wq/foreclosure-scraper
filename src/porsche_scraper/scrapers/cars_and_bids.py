"""Cars & Bids — Porsche auctions.

C&B's old public JSON endpoint (`/auctions/api/auctions`) silently
returns the SPA shell now; the real `/api/auctions` requires auth.
The rendered search page is the reliable path.

Each card is `<li class="auction-item">` with:
- `a.hero[title][href]`           — listing slug + clean title
- `.bid-value`                    — current bid ("$31,700")
- `.auction-subtitle`             — "~20,200 Miles, Twin-Turbo V6, ..."
- `.auction-loc`                  — seller city/state

We render `/search/porsche` once (60 cards) and also `/past-auctions/`
for recently-sold context. C&B sits behind DataDome, so Patchright
stealth via `fetch_rendered` is mandatory.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_rendered
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

BASE = "https://carsandbids.com"
SEARCH_URL = f"{BASE}/search/porsche"
EXCLUDED_MODELS_LOWER = ("panamera", "macan")


def parse_search_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for li in tree.css("li.auction-item"):
        hero = li.css_first("a.hero")
        if not hero:
            continue
        href = hero.attributes.get("href") or ""
        if not href:
            continue
        url = href if href.startswith("http") else urljoin(BASE, href)
        url = url.split("?")[0]  # strip the ss_id tracking param
        if url in seen:
            continue
        seen.add(url)
        title = hero.attributes.get("title") or ""
        if not title:
            title_node = li.css_first(".auction-title a")
            if title_node:
                title = title_node.text(strip=True)
        if not title or "porsche" not in title.lower():
            continue
        title_l = title.lower()
        if any(em in title_l for em in EXCLUDED_MODELS_LOWER):
            continue
        bid_node = li.css_first(".bid-value")
        bid_text = bid_node.text(strip=True) if bid_node else None
        subtitle_node = li.css_first(".auction-subtitle")
        subtitle = subtitle_node.text(strip=True) if subtitle_node else ""
        loc_node = li.css_first(".auction-loc")
        location = loc_node.text(strip=True) if loc_node else None
        img_node = li.css_first("img")
        photo = img_node.attributes.get("src") if img_node else None
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        listing = Listing(
            source="cars_and_bids",
            source_url=url,
            listing_id=slug or url,
            title=title,
            year=parse_year(title),
            current_bid_usd=parse_price(bid_text),
            mileage=parse_miles(subtitle),
            location=location,
            photo_url=photo,
            title_status=infer_title_status(title + " " + subtitle),
            seller_type="auction",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


class CarsAndBidsScraper(BaseScraper):
    slug = "cars_and_bids"
    name = "Cars & Bids"
    timeout_s = 240.0

    def __init__(self, *, year_min: int = 2014, max_bid: int = 45000, max_pages: int = 1):
        # max_pages kept for signature compatibility; C&B's search page
        # is a single virtualised list, no pagination needed.
        self.year_min = year_min
        self.max_bid = max_bid

    async def fetch(self) -> list[Listing]:
        try:
            html = await fetch_rendered(
                SEARCH_URL, timeout=60,
                wait_for_selector="li.auction-item, a.hero",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("cars_and_bids fetch failed: %s", exc)
            return []
        out: list[Listing] = []
        seen: set[str] = set()
        for listing in parse_search_html(html):
            if listing.source_url in seen:
                continue
            seen.add(listing.source_url)
            if listing.year is not None and listing.year < self.year_min:
                continue
            out.append(listing)
        return out


# Back-compat shims for any external test that still imported the
# old helpers. Both delegate to the rendered-HTML path now.
def parse_results(payload):  # noqa: D401
    if isinstance(payload, str):
        return parse_search_html(payload)
    return []
