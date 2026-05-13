"""Bring a Trailer — Porsche auctions (live + recently completed).

BaT lists Porsche auctions under https://bringatrailer.com/porsche/ with
sub-paths per model (911, 718, cayman, boxster, …). Each model page is
paginated /page/2/, /page/3/ ….

The listings grid embeds a JS variable `auctionsCompletedInitialData` (a
JSON array of objects with sold price, year, model, image, link, etc.)
in a `<script>` tag - we use that as the primary parser. We avoid the
model paths that are excluded (cayenne, macan, panamera).

BaT sits behind Cloudflare; we use the stealth (curl-cffi) transport.
"""
from __future__ import annotations

import json
import logging
import re
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

BASE = "https://bringatrailer.com"

# We only crawl model paths we care about. BaT's category slugs.
PORSCHE_MODEL_PATHS = (
    "/porsche/911/",
    "/porsche/718-cayman/",
    "/porsche/cayman/",
    "/porsche/718-boxster/",
    "/porsche/boxster/",
    "/porsche/944/",
    "/porsche/928/",
    "/porsche/924/",
    "/porsche/968/",
)

_AUCTION_DATA_RE = re.compile(
    r"auctionsCompletedInitialData\s*=\s*(\[.*?\]);", re.DOTALL
)
_ACTIVE_DATA_RE = re.compile(
    r"(?:activeAuctionData|featured_listings)\s*=\s*(\[.*?\]);", re.DOTALL
)


def _extract_embedded(html: str) -> list[dict]:
    out: list[dict] = []
    for pattern in (_AUCTION_DATA_RE, _ACTIVE_DATA_RE):
        m = pattern.search(html)
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(arr, list):
            out.extend(d for d in arr if isinstance(d, dict))
    return out


def _listing_from_embedded(d: dict) -> Listing | None:
    url = d.get("url") or d.get("permalink")
    title = d.get("title") or d.get("name") or ""
    if not url or not title:
        return None
    url = urljoin(BASE, url)
    year = d.get("year") or parse_year(title)
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = parse_year(title)
    # BaT uses "current_bid", "sold_price", "amount" depending on state.
    price = (
        parse_price(d.get("current_bid"))
        or parse_price(d.get("sold_price"))
        or parse_price(d.get("amount"))
    )
    miles = parse_miles(d.get("mileage") or d.get("odometer"))
    image = None
    if isinstance(d.get("images"), list) and d["images"]:
        first = d["images"][0]
        image = first if isinstance(first, str) else first.get("url")
    image = image or d.get("image") or d.get("thumbnail")
    listing = Listing(
        source="bring_a_trailer",
        source_url=url,
        listing_id=str(d.get("id") or d.get("ID") or url),
        title=title,
        year=year,
        model=d.get("model"),
        current_bid_usd=price,
        mileage=miles,
        location=d.get("location") or d.get("seller_location"),
        photo_url=image,
        title_status=infer_title_status(title + " " + (d.get("excerpt") or "")),
        seller_type="auction",
        raw={"bat": d},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


def _listings_from_html(html: str) -> Iterable[Listing]:
    tree = HTMLParser(html)
    for card in tree.css(".listing-card, article.auction-item"):
        a = card.css_first(".content-title a") or card.css_first("a[href]")
        if not a:
            continue
        href = a.attributes.get("href")
        if not href:
            continue
        title = a.text(strip=True)
        bid = card.css_first(".bid-formatted") or card.css_first(".td-price")
        loc = card.css_first(".item-location") or card.css_first(".listing-card-subheading")
        img = card.css_first("img")
        listing = Listing(
            source="bring_a_trailer",
            source_url=urljoin(BASE, href),
            title=title,
            year=parse_year(title),
            current_bid_usd=parse_price(bid.text(strip=True)) if bid else None,
            location=loc.text(strip=True) if loc else None,
            photo_url=(img.attributes.get("data-src") or img.attributes.get("src")) if img else None,
            title_status=infer_title_status(title),
            seller_type="auction",
        )
        listing.drivable = infer_drivable(listing.title, listing.title_status)
        yield listing


def parse_index_page(html: str) -> list[Listing]:
    """Parse one BaT model-index page. Tries embedded JSON, then HTML."""
    seen: set[str] = set()
    out: list[Listing] = []
    for d in _extract_embedded(html):
        listing = _listing_from_embedded(d)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    if out:
        return out
    for listing in _listings_from_html(html):
        if listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class BringATrailerScraper(BaseScraper):
    slug = "bring_a_trailer"
    name = "Bring a Trailer"
    timeout_s = 180.0

    def __init__(self, *, max_pages_per_model: int = 3):
        self.max_pages_per_model = max_pages_per_model

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for path in PORSCHE_MODEL_PATHS:
            for page in range(1, self.max_pages_per_model + 1):
                url = urljoin(BASE, path) if page == 1 else urljoin(BASE, f"{path}page/{page}/")
                try:
                    html = await fetch_text_stealth(url, timeout=60)
                except Exception as exc:  # noqa: BLE001
                    log.warning("bat %s page %d failed: %s", path, page, exc)
                    break
                listings = parse_index_page(html)
                if not listings:
                    break
                out.extend(listings)
        return out
