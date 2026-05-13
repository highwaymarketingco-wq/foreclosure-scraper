"""Cars & Bids — Porsche auctions.

C&B is a SPA. We use two paths:

1. Their public JSON endpoint (no auth needed):
       https://carsandbids.com/auctions/api/auctions?search=porsche&minYear=2014&maxBid=45000
   Returns `{ auctions: [...] }`. Each auction has title, year, make,
   model, currentBid/buyNowPrice, mileage, location, slug, images,
   titleStatus.

2. Fallback: server-rendered shell page with `<script id="__NEXT_DATA__">`
   carrying the same data tree at `props.pageProps.auctions`.

C&B sits behind DataDome so we use the stealth transport.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_text_stealth
from ..models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
)

log = logging.getLogger(__name__)

BASE = "https://carsandbids.com"


def _title_status(raw: str | None) -> TitleStatus:
    if not raw:
        return TitleStatus.UNKNOWN
    s = raw.lower()
    if "rebuilt" in s or "reconstructed" in s:
        return TitleStatus.REBUILT
    if "salvage" in s:
        return TitleStatus.SALVAGE
    if "clean" in s or "clear" in s:
        return TitleStatus.CLEAN
    return infer_title_status(raw)


def _listing_from_api(d: dict) -> Listing | None:
    slug = d.get("slug") or d.get("url")
    if not slug:
        return None
    url = slug if slug.startswith("http") else urljoin(BASE, f"/auctions/{slug}")
    title = d.get("title") or " ".join(
        filter(None, [str(d.get("year") or ""), d.get("make") or "", d.get("model") or ""])
    )
    images = d.get("images") or []
    first_img = None
    if images:
        first = images[0]
        first_img = first.get("url") if isinstance(first, dict) else first
    listing = Listing(
        source="cars_and_bids",
        source_url=url,
        listing_id=str(d.get("id") or slug),
        title=title,
        year=d.get("year") or None,
        model=d.get("model"),
        current_bid_usd=parse_price(d.get("currentBid") or d.get("highBid")),
        price_usd=parse_price(d.get("buyNowPrice")),
        mileage=parse_miles(d.get("mileage") or d.get("odometer")),
        location=d.get("sellerLocation") or d.get("location"),
        photo_url=first_img,
        title_status=_title_status(d.get("titleStatus") or title),
        seller_type="auction",
        raw={"cb": d},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _extract_next_data(html: str) -> list[dict]:
    tree = HTMLParser(html)
    node = tree.css_first('script#__NEXT_DATA__')
    if not node:
        return []
    try:
        blob = json.loads(node.text() or "{}")
    except json.JSONDecodeError:
        return []
    pp = ((blob.get("props") or {}).get("pageProps") or {})
    cand = pp.get("auctions") or pp.get("listings") or []
    if isinstance(cand, list):
        return [d for d in cand if isinstance(d, dict)]
    return []


def parse_results(payload: dict | str) -> list[Listing]:
    """Parse a C&B JSON response or HTML page into Listings."""
    items: Iterable[dict]
    if isinstance(payload, dict):
        items = payload.get("auctions") or payload.get("results") or payload.get("data") or []
    else:
        items = _extract_next_data(payload)
    out: list[Listing] = []
    seen: set[str] = set()
    for d in items:
        listing = _listing_from_api(d)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class CarsAndBidsScraper(BaseScraper):
    slug = "cars_and_bids"
    name = "Cars & Bids"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, max_bid: int = 45000, max_pages: int = 10):
        self.year_min = year_min
        self.max_bid = max_bid
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            params = {
                "search": "porsche",
                "minYear": self.year_min,
                "maxBid": self.max_bid,
                "page": page,
                "sort": "endingSoonest",
            }
            url = f"{BASE}/auctions/api/auctions?{urlencode(params)}"
            try:
                raw = await fetch_text_stealth(url, timeout=45, headers={"Accept": "application/json"})
            except Exception as exc:  # noqa: BLE001
                log.warning("cars_and_bids page %d failed: %s", page, exc)
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Probably got an HTML challenge page; try the SPA shell instead.
                shell = await fetch_text_stealth(
                    f"{BASE}/search/porsche?page={page}", timeout=45
                )
                listings = parse_results(shell)
            else:
                listings = parse_results(data)
            if not listings:
                break
            out.extend(listings)
        # Also pull rebuilt/salvage results regardless of price.
        for page in range(1, 3):
            url = f"{BASE}/auctions/api/auctions?{urlencode({'search': 'porsche', 'titleStatus': 'salvage', 'page': page})}"
            try:
                raw = await fetch_text_stealth(url, timeout=45, headers={"Accept": "application/json"})
                data = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                log.info("cars_and_bids salvage pass skipped: %s", exc)
                break
            out.extend(parse_results(data))
        return out
