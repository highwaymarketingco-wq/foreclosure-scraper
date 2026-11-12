"""ClassicCars.com — sitemap-driven discovery.

ClassicCars sitemap_index.xml points to ccpublic.blob.core.windows.net
sub-sitemaps. The `sitemap_listings_N.xml.gz` files contain ~500 URLs
each (78 total ≈ ~39,000 vehicles across all makes). Each URL is
`/listings/view/{id}/{year}-{make}-{model}-for-sale-in-{city}-{state}-{zip}`.

Slug carries year, make, and model. We filter to porsche + year ≥ 2014
+ wanted model from the slug alone, then optionally enrich a sample of
detail pages for price + photo.
"""
from __future__ import annotations

import logging
import re

from ..base import BaseScraper
from ..http_client import fetch_text_stealth
from ..models import Listing, infer_drivable, infer_title_status, parse_price
from ..sitemap_discovery import fetch_details_concurrently, walk_sitemap

log = logging.getLogger(__name__)

INDEX_URL = "https://classiccars.com/sitemap_index.xml"

# /listings/view/1334127/2000-porsche-boxster-for-sale-in-mansfield-texas-76063
_SLUG_RE = re.compile(
    r"/listings/view/(?P<id>\d+)/(?P<year>(?:19|20)\d{2})-porsche-(?P<model>[a-z0-9-]+?)-for-sale",
    re.IGNORECASE,
)
EXCLUDED_SLUG_TOKENS = ("macan", "panamera")

# ClassicCars embeds price in a JSON-LD Vehicle blob.
_JSONLD_PRICE_RE = re.compile(r'"price"\s*:\s*"?(\d[\d.,]*)"?')
_OG_IMAGE_RE = re.compile(r'<meta\s+property="og:image"\s+content="([^"]+)"', re.IGNORECASE)
_OG_TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]+)"', re.IGNORECASE)
_LOCATION_RE = re.compile(r'"address"\s*:\s*"([^"]+)"|in\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+[A-Z][a-z]+)')


def _listing_from_url(url: str) -> Listing | None:
    m = _SLUG_RE.search(url)
    if not m:
        return None
    raw_model = m.group("model").lower()
    if any(t in raw_model for t in EXCLUDED_SLUG_TOKENS):
        return None
    year = int(m.group("year"))
    model = " ".join(w.capitalize() if not w.isdigit() else w for w in raw_model.split("-"))
    title = f"{year} Porsche {model}"
    listing = Listing(
        source="classiccars_com",
        source_url=url,
        listing_id=m.group("id"),
        title=title,
        year=year,
        model=model,
        title_status=infer_title_status(title),
        seller_type="private",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


def _enrich_from_html(listing: Listing, html: str) -> Listing:
    img = _OG_IMAGE_RE.search(html)
    if img:
        listing.photo_url = img.group(1)
    title_m = _OG_TITLE_RE.search(html)
    if title_m:
        listing.title = title_m.group(1).rsplit(" - ", 1)[0]
    price_m = _JSONLD_PRICE_RE.search(html)
    if price_m:
        try:
            v = float(price_m.group(1).replace(",", ""))
            if 100 < v < 10_000_000:
                listing.price_usd = v
        except ValueError:
            pass
    return listing


class ClassicCarsSitemapScraper(BaseScraper):
    slug = "classiccars_sitemap"
    name = "ClassicCars.com (sitemap)"
    timeout_s = 600.0

    def __init__(
        self,
        *,
        year_min: int = 2014,
        max_urls: int = 800,
        max_detail_fetches: int = 200,
    ):
        self.year_min = year_min
        self.max_urls = max_urls
        self.max_detail_fetches = max_detail_fetches

    async def fetch(self) -> list[Listing]:
        candidates: list[Listing] = []
        seen: set[str] = set()
        async for url in walk_sitemap(INDEX_URL, max_children=80):
            if "porsche" not in url.lower() or "/listings/view/" not in url:
                continue
            if url in seen:
                continue
            seen.add(url)
            listing = _listing_from_url(url)
            if not listing or listing.year is None or listing.year < self.year_min:
                continue
            candidates.append(listing)
            if len(candidates) >= self.max_urls:
                break
        log.info("classiccars sitemap: %d candidate URLs after slug-filter", len(candidates))

        sample = candidates[: self.max_detail_fetches]

        async def fetch_one(listing: Listing):
            try:
                html = await fetch_text_stealth(listing.source_url, timeout=20)
                return _enrich_from_html(listing, html)
            except Exception:
                return listing

        enriched = await fetch_details_concurrently(sample, fetch_one, max_concurrency=6)
        return list(enriched) + candidates[self.max_detail_fetches :]
