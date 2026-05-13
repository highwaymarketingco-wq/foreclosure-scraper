"""Elferspot — sitemap-driven discovery.

Elferspot exposes its full vehicle inventory under
`/fahrzeug_en-sitemap{N}.xml`. Each URL slug is
`/en/car/porsche-{model}-{year}-{listing_id}/` — year and model parse
cleanly from the slug without fetching the detail page.

This pulls ~5,000–30,000 Porsche URLs from the sitemap, filters to the
user criteria (2014+, exclude Cayenne/Macan/Panamera) from the slug
alone, then optionally fetches detail pages to enrich with price + photo.

Detail-page price lookup is bandwidth-heavy (158 KB each); we cap it
via `max_detail_fetches` so a full run finishes in minutes, not hours.
"""
from __future__ import annotations

import logging
import re

from ..base import BaseScraper
from ..http_client import fetch_text_stealth
from ..models import Listing, TitleStatus, infer_drivable, infer_title_status, parse_price
from ..sitemap_discovery import SlugParser, fetch_details_concurrently, walk_sitemap

log = logging.getLogger(__name__)

INDEX_URL = "https://www.elferspot.com/sitemap_index.xml"

# elferspot URLs always contain the year and model right before the listing id:
#   /en/car/porsche-911-carrera-4s-2013-36482/
#   /en/car/porsche-997-2-gt3-2010-19402/
_SLUG_RE = re.compile(
    r"/car/porsche-(?P<model>[a-z0-9-]+?)-(?P<year>(?:19|20)\d{2})-\d+/?",
    re.IGNORECASE,
)
_SLUG_PARSER = SlugParser(_SLUG_RE, model_aliases={})
EXCLUDED_SLUG_TOKENS = ("cayenne", "macan", "panamera")


def _model_from_slug(raw: str) -> str:
    """Turn elferspot's '911-carrera-4s' into a display 'Porsche 911 Carrera 4S'."""
    if not raw:
        return ""
    return "Porsche " + " ".join(w.capitalize() if not w.isdigit() else w for w in raw.split("-"))


def _listing_from_url(url: str) -> Listing | None:
    year, raw_model = _SLUG_PARSER.parse(url)
    if not year or not raw_model:
        return None
    if any(t in raw_model.lower() for t in EXCLUDED_SLUG_TOKENS):
        return None
    title = _model_from_slug(raw_model) + f" ({year})"
    listing_id = url.rstrip("/").rsplit("-", 1)[-1]
    listing = Listing(
        source="elferspot",
        source_url=url,
        listing_id=listing_id,
        title=title,
        year=year,
        model=raw_model.split("-")[0].upper() if raw_model else None,
        title_status=infer_title_status(title),
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


# ---- Detail-page price enrichment ----

_OG_IMAGE_RE = re.compile(r'<meta\s+property="og:image"\s+content="([^"]+)"', re.IGNORECASE)
_OG_TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]+)"', re.IGNORECASE)
_PRICE_PATTERNS = (
    re.compile(r'"price"\s*:\s*"?([\d.]+)"?'),
    re.compile(r'price[^<>"]*?€\s*([\d.,]+)', re.IGNORECASE),
    re.compile(r'EUR\s*([\d.,]+)'),
    re.compile(r'>€\s*([\d.,]+)<'),
    re.compile(r'>\s*\$\s*([\d.,]+)\s*<'),
)


def _enrich_from_html(listing: Listing, html: str, fx: float) -> Listing:
    img = _OG_IMAGE_RE.search(html)
    if img:
        listing.photo_url = img.group(1)
    title = _OG_TITLE_RE.search(html)
    if title:
        # og:title is like "For sale: Porsche 911 Carrera 4S 2013 - elferspot.com"
        clean = title.group(1).replace("For sale: ", "").rsplit(" - ", 1)[0]
        if clean:
            listing.title = clean
    for pat in _PRICE_PATTERNS:
        m = pat.search(html)
        if not m:
            continue
        raw = m.group(1).replace(".", "").replace(",", "")
        try:
            price_eur = float(raw)
            if 1000 < price_eur < 10_000_000:  # Sanity bound.
                listing.price_usd = price_eur * fx
                listing.raw = {**(listing.raw or {}), "price_eur": price_eur}
                break
        except ValueError:
            continue
    return listing


class ElferspotSitemapScraper(BaseScraper):
    slug = "elferspot_sitemap"
    name = "Elferspot (sitemap)"
    timeout_s = 600.0

    def __init__(
        self,
        *,
        year_min: int = 2014,
        max_urls: int = 800,
        max_detail_fetches: int = 200,
        eur_to_usd: float = 1.08,
    ):
        self.year_min = year_min
        self.max_urls = max_urls
        self.max_detail_fetches = max_detail_fetches
        self.fx = eur_to_usd

    async def fetch(self) -> list[Listing]:
        # 1. Walk the sitemap index, collect candidate Porsche URLs.
        candidates: list[Listing] = []
        seen: set[str] = set()
        async for url in walk_sitemap(INDEX_URL, use_stealth=True, max_children=20):
            if "/car/porsche-" not in url.lower():
                continue
            if url in seen:
                continue
            seen.add(url)
            listing = _listing_from_url(url)
            if not listing:
                continue
            if listing.year is None or listing.year < self.year_min:
                continue
            candidates.append(listing)
            if len(candidates) >= self.max_urls:
                break
        log.info("elferspot sitemap: %d candidate URLs after slug-filter", len(candidates))

        # 2. Enrich a sample with detail-page price+photo via concurrent fetches.
        sample = candidates[: self.max_detail_fetches]

        async def fetch_one(listing: Listing):
            try:
                html = await fetch_text_stealth(listing.source_url, timeout=20)
                return _enrich_from_html(listing, html, self.fx)
            except Exception:
                return listing  # Keep the URL-only record.

        enriched = await fetch_details_concurrently(sample, fetch_one, max_concurrency=6)
        # Append the URL-only tail for max coverage.
        return list(enriched) + candidates[self.max_detail_fetches :]
