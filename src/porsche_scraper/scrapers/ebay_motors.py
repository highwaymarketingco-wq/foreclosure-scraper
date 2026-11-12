"""eBay Motors — Porsche listings.

Search URL pattern (used cars / 6001):
    https://www.ebay.com/sch/Cars-Trucks/6001/i.html
        ?_nkw=porsche
        &_udhi=45000              # price ceiling
        &Model%20Year=2014|2015|...  # year filter via aspect
        &_ipg=200                 # items per page
        &_pgn=N                   # page number

eBay HTML lists results as <li class="s-item">. We parse those directly.
A separate pass with `LH_TitleType=1` (rebuilt/salvage) is unioned for
the title-status case.

If EBAY_OAUTH_TOKEN is in env we additionally hit the Browse API which is
much more reliable (returns clean JSON). Browse API isn't required.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_json, fetch_text
from ..models import (
    Listing,
    infer_drivable,
    infer_title_status,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://www.ebay.com"

# eBay Motors category for "Cars & Trucks"
CARS_TRUCKS_CATEGORY = "6001"


def _year_aspect(year_min: int, year_max: int) -> str:
    return "|".join(str(y) for y in range(year_min, year_max + 1))


def _build_html_url(*, year_min: int, year_max: int, price_max: int | None, page: int) -> str:
    params = {
        "_nkw": "porsche",
        "_ipg": 200,
        "_pgn": page,
        # 3000 = used; LH_ItemCondition multi-value as comma-sep
        "LH_ItemCondition": "3000",
        "Model%20Year": _year_aspect(year_min, year_max),
    }
    if price_max is not None:
        params["_udhi"] = price_max
    qs = urlencode(params, safe="|")
    return f"{BASE}/sch/Cars-Trucks/{CARS_TRUCKS_CATEGORY}/i.html?{qs}"


_SUBTITLE_RE = re.compile(r"(\d[\d,]*)\s*Miles?", re.IGNORECASE)


def _listing_from_card(card) -> Listing | None:
    link = card.css_first("a.s-item__link") or card.css_first("a[href]")
    if not link:
        return None
    url = link.attributes.get("href")
    if not url or "itm/" not in url:
        return None
    title_node = card.css_first(".s-item__title")
    title = title_node.text(strip=True) if title_node else ""
    if title.lower().startswith("shop on ebay"):
        return None  # eBay's promo row.
    price_node = card.css_first(".s-item__price")
    sub = card.css_first(".s-item__subtitle")
    miles = None
    if sub:
        m = _SUBTITLE_RE.search(sub.text() or "")
        if m:
            miles = int(m.group(1).replace(",", ""))
    loc_node = card.css_first(".s-item__location") or card.css_first(".s-item__itemLocation")
    img = card.css_first(".s-item__image-img") or card.css_first("img")
    listing = Listing(
        source="ebay_motors",
        source_url=url.split("?")[0],
        listing_id=_ebay_item_id(url),
        title=title,
        year=parse_year(title),
        price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
        mileage=miles,
        location=loc_node.text(strip=True) if loc_node else None,
        photo_url=(img.attributes.get("data-src") or img.attributes.get("src")) if img else None,
        title_status=infer_title_status(title),
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _ebay_item_id(url: str) -> str | None:
    m = re.search(r"/itm/(?:[^/]+/)?(\d{9,})", url)
    return m.group(1) if m else None


def parse_results_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for card in tree.css("li.s-item"):
        listing = _listing_from_card(card)
        if listing and listing.listing_id and listing.listing_id not in seen:
            seen.add(listing.listing_id)
            out.append(listing)
    return out


async def _browse_api_search(
    *, token: str, year_min: int, year_max: int, price_max: int | None
) -> Iterable[Listing]:
    """eBay Browse API — much cleaner than HTML if OAuth is available."""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    price_clause = f",price:[..{price_max}]" if price_max else ""
    filt = (
        f"categoryIds:{{{CARS_TRUCKS_CATEGORY}}},"
        f"conditionIds:{{3000}}"
        f"{price_clause}"
    )
    aspects = f"Model Year:{{{_year_aspect(year_min, year_max)}}}"
    params = {
        "q": "porsche",
        "limit": 200,
        "filter": filt,
        "aspect_filter": f"categoryId:{CARS_TRUCKS_CATEGORY},{aspects}",
    }
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urlencode(params)
    data = await fetch_json(url, headers=headers, timeout=45)
    for item in data.get("itemSummaries") or []:
        url = item.get("itemWebUrl")
        title = item.get("title") or ""
        listing = Listing(
            source="ebay_motors",
            source_url=url or "",
            listing_id=item.get("itemId"),
            title=title,
            year=parse_year(title),
            price_usd=parse_price((item.get("price") or {}).get("value")),
            location=(item.get("itemLocation") or {}).get("city"),
            photo_url=(item.get("image") or {}).get("imageUrl"),
            title_status=infer_title_status(title),
            seller_type="dealer",
        )
        listing.drivable = infer_drivable(listing.title, listing.title_status)
        if listing.source_url:
            yield listing


class EbayMotorsScraper(BaseScraper):
    slug = "ebay_motors"
    name = "eBay Motors"
    timeout_s = 180.0

    def __init__(
        self,
        *,
        year_min: int = 2014,
        year_max: int | None = None,
        price_max: int | None = 45000,
        max_pages: int = 10,
    ):
        from ..filters import current_year
        self.year_min = year_min
        self.year_max = year_max or current_year()
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        token = os.environ.get("EBAY_OAUTH_TOKEN")
        if token:
            try:
                async for listing in _browse_api_search(
                    token=token,
                    year_min=self.year_min,
                    year_max=self.year_max,
                    price_max=self.price_max,
                ):
                    out.append(listing)
            except Exception as exc:  # noqa: BLE001
                log.warning("ebay browse api failed, falling back to HTML: %s", exc)
        if out:
            return out
        for page in range(1, self.max_pages + 1):
            url = _build_html_url(
                year_min=self.year_min,
                year_max=self.year_max,
                price_max=self.price_max,
                page=page,
            )
            try:
                html = await fetch_text(url, timeout=45)
            except Exception as exc:  # noqa: BLE001
                log.warning("ebay page %d failed: %s", page, exc)
                break
            page_listings = parse_results_html(html)
            if not page_listings:
                break
            out.extend(page_listings)
        return out
