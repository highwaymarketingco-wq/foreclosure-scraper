"""autotrader.com — Porsche listings.

URL:
    https://www.autotrader.com/cars-for-sale/all-cars/porsche
        ?maxPrice=45000&startYear=2014&searchRadius=0

Autotrader server-renders an `__NEXT_DATA__` script with the full
inventory tree at `props.pageProps.initialState.inventory.listings`.
Heavy Cloudflare protection — uses stealth + proxies.
"""
from __future__ import annotations

import json
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

BASE = "https://www.autotrader.com"


def _listing_from_at(item: dict) -> Listing | None:
    url = item.get("websiteUrl") or item.get("vdpUrl") or item.get("vehicleDetailUrl")
    if not url:
        return None
    url = urljoin(BASE, url)
    title = item.get("title") or " ".join(
        filter(None, [str(item.get("year") or ""), item.get("make") or "", item.get("model") or ""])
    )
    price = parse_price(item.get("price") or (item.get("priceInfo") or {}).get("salePrice"))
    miles = parse_miles(item.get("mileage") or (item.get("specifications") or {}).get("mileage"))
    images = item.get("images") or {}
    img_list = images.get("sources") if isinstance(images, dict) else images
    photo = None
    if isinstance(img_list, list) and img_list:
        first = img_list[0]
        photo = first.get("src") if isinstance(first, dict) else first
    listing = Listing(
        source="autotrader",
        source_url=url,
        listing_id=str(item.get("id") or item.get("listingId") or item.get("vin") or url),
        vin=item.get("vin"),
        title=title,
        year=item.get("year") or parse_year(title),
        model=item.get("model"),
        trim=item.get("trim"),
        price_usd=price,
        mileage=miles,
        location=(item.get("ownerDealer") or item.get("owner") or {}).get("location")
        if isinstance(item.get("ownerDealer") or item.get("owner"), dict)
        else item.get("location"),
        photo_url=photo,
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"autotrader": item},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _extract_next_data_listings(html: str) -> list[dict]:
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")
    if not node:
        return []
    try:
        blob = json.loads(node.text() or "{}")
    except json.JSONDecodeError:
        return []
    # path: props.pageProps.initialState.inventory.listings
    cur = blob
    for k in ("props", "pageProps", "initialState", "inventory", "listings"):
        if not isinstance(cur, dict) or k not in cur:
            return []
        cur = cur[k]
    return cur if isinstance(cur, list) else []


def parse_results_html(html: str) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    for item in _extract_next_data_listings(html):
        listing = _listing_from_at(item)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class AutotraderScraper(BaseScraper):
    slug = "autotrader"
    name = "Autotrader"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, price_max: int | None = 45000, max_pages: int = 10):
        self.year_min = year_min
        self.price_max = price_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(self.max_pages):
            params = [
                "makeCodeList=POR",
                f"startYear={self.year_min}",
                "searchRadius=0",
                f"firstRecord={page * 100}",
                "numRecords=100",
            ]
            if self.price_max is not None:
                params.append(f"maxPrice={self.price_max}")
            url = f"{BASE}/cars-for-sale/all-cars/porsche?" + "&".join(params)
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001
                log.warning("autotrader page %d failed: %s", page, exc)
                break
            listings = parse_results_html(html)
            if not listings:
                break
            out.extend(listings)
        return out
