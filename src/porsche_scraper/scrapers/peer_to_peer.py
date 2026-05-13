"""Peer-to-peer classifieds — Facebook Marketplace + Craigslist.

Both are well-known anti-scraping targets:

- Facebook Marketplace requires a logged-in cookie and renders results
  via GraphQL XHRs. Without `FB_USER_COOKIE` set we return an empty
  list and log a hint. With it set, we hit the public marketplace search
  page and parse the embedded `RelayPrefetchedStreamCache` JSON.

- Craigslist requires per-region fan-out (each city has its own subdomain
  like `https://atlanta.craigslist.org/search/cta?query=porsche&...`)
  and aggressively 403s datacenter IPs. We crawl a small default city
  list; users override via `CRAIGSLIST_CITIES` env var (comma-separated
  subdomains).

Both are **off by default** — they're enabled only via the CLI
`--only craigslist fb_marketplace` flag, since they're slow and lossy.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable

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


# ---------- Facebook Marketplace ----------


class FacebookMarketplaceScraper(BaseScraper):
    """Best-effort FB Marketplace scraper.

    Requires:
      FB_USER_COOKIE — full cookie string from a logged-in browser
      FB_USER_AGENT  — optional, defaults to a Chrome UA

    Without these we log a hint and return [] so the rest of the pipeline
    isn't held up.
    """

    slug = "fb_marketplace"
    name = "Facebook Marketplace"
    timeout_s = 180.0

    def __init__(self, *, price_max: int = 45_000, year_min: int = 2014, max_pages: int = 3):
        self.price_max = price_max
        self.year_min = year_min
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        cookie = os.environ.get("FB_USER_COOKIE")
        if not cookie:
            log.info(
                "fb_marketplace skipped: set FB_USER_COOKIE (full cookie string "
                "from a logged-in browser) to enable this scraper."
            )
            return []
        headers = {
            "Cookie": cookie,
            "User-Agent": os.environ.get(
                "FB_USER_AGENT",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            ),
        }
        url = (
            "https://www.facebook.com/marketplace/category/cars/"
            f"?query=porsche&maxPrice={self.price_max}&minYear={self.year_min}"
        )
        try:
            html = await fetch_text_stealth(url, timeout=60, headers=headers)
        except Exception as exc:  # noqa: BLE001
            log.warning("fb_marketplace fetch failed: %s", exc)
            return []
        return list(parse_fb_html(html))


_FB_LISTING_RE = re.compile(r'"listing_id":"(\d+)"')
_FB_CONTEXT_LOOKAHEAD = 4096
_FB_CONTEXT_LOOKBEHIND = 1024


def _fb_unescape(s: str) -> str:
    if not s:
        return ""
    try:
        return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def parse_fb_html(html: str) -> Iterable[Listing]:
    """Parse FB Marketplace's embedded Relay JSON dumps. Best-effort.

    Anchors on `"listing_id":"<digits>"` and harvests the surrounding fields.
    FB ships Porsche listings via `RelayPrefetchedStreamCache` inside
    script tags. Regex over a wide context window beats trying to
    round-trip the whole dump.
    """
    seen: set[str] = set()
    for m in _FB_LISTING_RE.finditer(html):
        lid = m.group(1)
        if lid in seen:
            continue
        seen.add(lid)
        start = max(0, m.start() - _FB_CONTEXT_LOOKBEHIND)
        end = min(len(html), m.end() + _FB_CONTEXT_LOOKAHEAD)
        chunk = html[start:end]

        title_m = re.search(r'"marketplace_listing_title":"([^"\\]*(?:\\.[^"\\]*)*)"', chunk)
        price_m = (
            re.search(r'"listing_price":\{"amount":"([\d.]+)"', chunk)
            or re.search(r'"formatted_price":\{[^}]*"text":"\$([\d,.]+)"', chunk)
        )
        image_m = (
            re.search(r'"primary_listing_photo":\{[^}]*?"image":\{"uri":"([^"]+)"', chunk)
            or re.search(r'"primary_photo_url":"([^"]+)"', chunk)
        )
        loc_m = (
            re.search(
                r'"location":\{[^}]*?"reverse_geocode":\{[^}]*?'
                r'"city_page":\{[^}]*?"display_name":"([^"]+)"',
                chunk,
            )
            or re.search(r'"location_text":\{"text":"([^"]+)"', chunk)
        )
        mileage_m = (
            re.search(r'"mileage":\{"value":(\d+)', chunk)
            or re.search(r'"odometer":\{"value":(\d+)', chunk)
        )
        year_m = re.search(r'"year":(\d{4})', chunk)
        vin_m = re.search(r'"vin":"([A-HJ-NPR-Z0-9]{17})"', chunk)

        title = _fb_unescape(title_m.group(1) if title_m else "")
        if "porsche" not in title.lower():
            continue
        if any(em in title.lower() for em in ("panamera", "cayenne", "macan")):
            continue

        year_val = int(year_m.group(1)) if year_m else parse_year(title)
        mileage_val = parse_miles(mileage_m.group(1)) if mileage_m else parse_miles(title)
        price_val = parse_price(price_m.group(1)) if price_m else None
        listing = Listing(
            source="fb_marketplace",
            source_url=f"https://www.facebook.com/marketplace/item/{lid}/",
            listing_id=lid,
            vin=vin_m.group(1) if vin_m else None,
            title=title,
            year=year_val,
            mileage=mileage_val,
            price_usd=price_val,
            location=(loc_m.group(1) if loc_m else None),
            photo_url=_fb_unescape(image_m.group(1)) if image_m else None,
            title_status=infer_title_status(title),
            seller_type="private",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        yield listing


# ---------- Craigslist ----------


# A small starter set; users override via CRAIGSLIST_CITIES env var.
DEFAULT_CRAIGSLIST_CITIES = (
    "newyork", "losangeles", "chicago", "houston", "phoenix",
    "philadelphia", "sanantonio", "sandiego", "dallas", "sanjose",
    "austin", "jacksonville", "fortworth", "columbus", "charlotte",
    "miami", "seattle", "denver", "boston", "atlanta",
)


class CraigslistScraper(BaseScraper):
    """Craigslist Porsche search across a list of city subdomains.

    Set CRAIGSLIST_CITIES="atlanta,charlotte,miami" to override.
    """

    slug = "craigslist"
    name = "Craigslist"
    timeout_s = 240.0

    def __init__(self, *, price_max: int = 45_000, year_min: int = 2014):
        self.price_max = price_max
        self.year_min = year_min

    @property
    def cities(self) -> tuple[str, ...]:
        env = os.environ.get("CRAIGSLIST_CITIES")
        if env:
            return tuple(c.strip() for c in env.split(",") if c.strip())
        return DEFAULT_CRAIGSLIST_CITIES

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for city in self.cities:
            url = (
                f"https://{city}.craigslist.org/search/cta"
                f"?query=porsche&min_price=1&max_price={self.price_max}"
                f"&min_auto_year={self.year_min}"
            )
            try:
                html = await fetch_text_stealth(url, timeout=45)
            except Exception as exc:  # noqa: BLE001
                log.info("craigslist %s skipped: %s", city, exc)
                continue
            for l in parse_craigslist_html(html, city):
                if l.source_url in seen:
                    continue
                seen.add(l.source_url)
                out.append(l)
        return out


def parse_craigslist_html(html: str, city: str) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    for li in tree.css("li.cl-static-search-result, li.result-row, div.cl-search-result"):
        a = li.css_first("a[href*='/cto/']") or li.css_first("a[href*='/d/']") or li.css_first("a.titlestring") or li.css_first("a")
        if not a:
            continue
        url = a.attributes.get("href") or ""
        if not url:
            continue
        title = a.text(strip=True)
        if "porsche" not in title.lower():
            continue
        price_node = li.css_first(".price") or li.css_first(".result-price")
        loc_node = li.css_first(".location") or li.css_first(".result-hood")
        listing = Listing(
            source="craigslist",
            source_url=url,
            listing_id=re.search(r"/(\d{8,})/?", url).group(1) if re.search(r"/(\d{8,})/?", url) else None,
            title=title,
            year=parse_year(title),
            price_usd=parse_price(price_node.text(strip=True)) if price_node else None,
            location=(loc_node.text(strip=True) if loc_node else f"{city} (CL)"),
            title_status=infer_title_status(title),
            seller_type="private",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out
