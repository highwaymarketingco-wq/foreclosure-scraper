"""PCARMARKET — Porsche-focused online auctions + fixed-price marketplace.

PCARMARKET rebuilt the search-results page as a Vite SPA: the main
grid is client-fetched and never lands in the static HTML, but the
server still renders a 24-item sidebar of related auctions in the SEO
shell. Each sidebar entry is a single `<a href="/auction/<slug>">` whose
text follows the pattern:

    "<title> — <status> $<price>"

We harvest the sidebar items as a low-effort first pass. The full
inventory is in `https://www.pcarmarket.com/sitemap.xml` (28k URLs);
hooking that up is left for future work.

Sits behind a light Cloudflare layer — curl-cffi `chrome124` is enough.
"""
from __future__ import annotations

import logging
import re
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

BASE = "https://www.pcarmarket.com"
SEARCH_PATHS = (
    "/auctions?search=porsche&status=active",
    "/auctions?search=porsche&status=ended",
    "/marketplace?search=porsche",
)
EXCLUDED_MODELS_LOWER = ("panamera", "cayenne", "macan")

# Title/status/price are jammed into a single anchor text. The em-dash
# `—` (or hyphen "-" fallback) separates the title from the status +
# price suffix.
_ANCHOR_SUFFIX_RE = re.compile(r"\s*[—-]\s*(\w+)\s+\$([\d,]+)\s*$")


def parse_results_html(html: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for a in tree.css('a[href*="/auction/"]'):
        href = a.attributes.get("href") or ""
        if not href:
            continue
        url = urljoin(BASE, href.split("?")[0])
        if url in seen:
            continue
        anchor_text = a.text(strip=True)
        if not anchor_text or "porsche" not in anchor_text.lower():
            continue
        if any(em in anchor_text.lower() for em in EXCLUDED_MODELS_LOWER):
            continue
        seen.add(url)
        # Strip the trailing "— Active $40,000" so the title is clean.
        title = anchor_text
        status_word = None
        price_text = None
        m = _ANCHOR_SUFFIX_RE.search(anchor_text)
        if m:
            status_word = m.group(1)
            price_text = m.group(2)
            title = anchor_text[: m.start()].strip()
        listing = Listing(
            source="pcarmarket",
            source_url=url,
            listing_id=url.rstrip("/").rsplit("/", 1)[-1],
            title=title,
            year=parse_year(title),
            current_bid_usd=parse_price(price_text),
            mileage=parse_miles(title),
            title_status=infer_title_status(title),
            seller_type="auction",
            raw={"pcarmarket": {"status": status_word}} if status_word else {},
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


class PCarMarketScraper(BaseScraper):
    slug = "pcarmarket"
    name = "PCARMARKET"
    timeout_s = 120.0

    def __init__(self, *, max_pages: int = 5):
        # max_pages kept for signature compatibility — pagination on
        # the sidebar is unsupported, so a single fetch per path covers
        # whatever the SEO shell renders.
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for path in SEARCH_PATHS:
            url = urljoin(BASE, path)
            try:
                html = await fetch_text_stealth(
                    url, timeout=45, impersonate="chrome124"
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("pcarmarket %s: %s", path, exc)
                continue
            for listing in parse_results_html(html):
                if listing.source_url in seen:
                    continue
                seen.add(listing.source_url)
                out.append(listing)
        return out
