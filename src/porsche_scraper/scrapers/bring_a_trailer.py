"""Bring a Trailer — Porsche auctions.

Each model index page (e.g. `/porsche/911/`) renders `.listing-card` DOM
nodes server-side; we parse those directly. The embedded JS used to also
expose `auctionsCompletedInitialData`, but BaT moved that behind a REST
endpoint (`/wp-json/bringatrailer/1.0/data/listings-filter`) so HTML
parsing is the simpler current path.

We crawl a curated list of model paths to keep the request count down
and to naturally exclude Cayenne / Panamera / Macan at the URL level.
The master `/porsche/` index page covers anything we miss.

BaT sits behind Cloudflare — use the stealth (curl-cffi) transport and a
residential proxy at scale.
"""
from __future__ import annotations

import logging
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

# Model index paths we crawl. Cayenne / Macan / Panamera intentionally
# excluded. Some are sub-categories (`911-gt3`) inside the broader page,
# but BaT lists them as their own indexes too. 404s are non-fatal — BaT
# occasionally renames categories.
PORSCHE_MODEL_PATHS = (
    "/porsche/",
    "/porsche/911/",
    "/porsche/cayman/",
    "/porsche/boxster/",
    "/porsche/928/",
    "/porsche/924/",
    "/porsche/944/",
    "/porsche/968/",
    "/porsche/914/",
)


def _bid_or_sold_price(card) -> tuple[float | None, float | None]:
    """Return (current_bid, sold_price). Sold pages use "Sold for: $X"."""
    label_node = card.css_first(".bid-label")
    amount_node = card.css_first(".bid-formatted")
    if not amount_node:
        return None, None
    amount = parse_price(amount_node.text(strip=True))
    label = (label_node.text(strip=True) if label_node else "").lower()
    if "sold" in label:
        return None, amount
    return amount, None


def _listing_from_card(card) -> Listing | None:
    link = card.css_first("h3 a[href]") or card.css_first("a.image-overlay[href]")
    if not link:
        return None
    href = link.attributes.get("href")
    if not href or "/listing/" not in href:
        return None
    title = link.text(strip=True) or link.attributes.get("title") or ""
    img = card.css_first(".thumbnail img")
    excerpt_node = card.css_first(".item-excerpt")
    excerpt = excerpt_node.text(strip=True) if excerpt_node else ""
    current_bid, sold_price = _bid_or_sold_price(card)
    miles = parse_miles(excerpt)  # BaT excerpts often contain "X-mile" or "X,XXX-Mile"
    listing_id = card.attributes.get("data-listing_id") or href.rstrip("/").split("/")[-1]
    title_status = infer_title_status(title + " " + excerpt)
    listing = Listing(
        source="bring_a_trailer",
        source_url=urljoin(BASE, href),
        listing_id=str(listing_id),
        title=title,
        year=parse_year(title),
        current_bid_usd=current_bid,
        price_usd=sold_price,  # Sold-for treated as price_usd for filter purposes.
        mileage=miles,
        photo_url=(img.attributes.get("src") or img.attributes.get("data-src")) if img else None,
        title_status=title_status,
        seller_type="auction",
    )
    listing.drivable = infer_drivable(title + " " + excerpt, title_status)
    return listing


def parse_index_page(html: str) -> list[Listing]:
    """Parse one BaT model-index page into Listings."""
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[Listing] = []
    for card in tree.css(".listing-card"):
        listing = _listing_from_card(card)
        if not listing or not listing.title:
            continue
        if listing.source_url in seen:
            continue
        seen.add(listing.source_url)
        out.append(listing)
    return out


class BringATrailerScraper(BaseScraper):
    slug = "bring_a_trailer"
    name = "Bring a Trailer"
    timeout_s = 240.0

    def __init__(self, *, max_pages_per_model: int = 3):
        self.max_pages_per_model = max_pages_per_model

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for path in PORSCHE_MODEL_PATHS:
            for page in range(1, self.max_pages_per_model + 1):
                url = urljoin(BASE, path) if page == 1 else urljoin(BASE, f"{path}page/{page}/")
                try:
                    html = await fetch_text_stealth(url, timeout=60)
                except Exception as exc:  # noqa: BLE001
                    log.warning("bat %s page %d failed: %s", path, page, exc)
                    break
                page_listings = parse_index_page(html)
                fresh = [l for l in page_listings if l.source_url not in seen]
                if not fresh:
                    break  # End of pagination or duplicate page.
                seen.update(l.source_url for l in fresh)
                out.extend(fresh)
        return out
