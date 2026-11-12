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
    timeout_s = 600.0

    #: Marketplace search results load via GraphQL after render and paginate on
    #: scroll, so this drives a real logged-in browser. One query per model keeps
    #: each search tight and multiplies coverage; the search redirects to the
    #: cookie's home location automatically.
    QUERIES = ("porsche 911", "porsche cayman", "porsche boxster",
               "porsche 718", "porsche cayenne", "porsche")
    SCROLLS = 8

    def __init__(self, *, price_max: int = 40_000, year_min: int = 2014, max_pages: int = 3):
        self.price_max = price_max
        self.year_min = year_min
        self.max_pages = max_pages

    @staticmethod
    def _load_cookie() -> str | None:
        """FB_USER_COOKIE env wins; otherwise ~/.porsche_fb_cookie (one line).

        The file path lets the operator set the cookie once instead of exporting
        it into every shell. Whitespace and a leading `Cookie:` label are
        stripped so pasting the raw request header just works.
        """
        cookie = os.environ.get("FB_USER_COOKIE")
        if not cookie:
            path = os.path.expanduser("~/.porsche_fb_cookie")
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as fh:
                        cookie = fh.read()
                except OSError:
                    cookie = None
        if not cookie:
            return None
        cookie = cookie.strip()
        if cookie.lower().startswith("cookie:"):
            cookie = cookie.split(":", 1)[1].strip()
        return cookie or None

    @staticmethod
    def _cookie_pairs(cookie: str) -> list[dict]:
        """Cookie header string -> Playwright cookie objects on .facebook.com."""
        out = []
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k:
                    out.append({"name": k, "value": v,
                                "domain": ".facebook.com", "path": "/"})
        return out

    # DOM extractor: every marketplace item card is an <a href="/marketplace/
    # item/<id>/">, whose innerText is price(s) + title + location (+ miles),
    # newline-separated. Scroll-loaded cards are real DOM, not JSON, so this
    # reads the rendered page rather than the Relay blob.
    _JS_EXTRACT = """() => {
      const out = [], seen = new Set();
      document.querySelectorAll('a[href*="/marketplace/item/"]').forEach(a => {
        const m = a.href.match(/\\/marketplace\\/item\\/(\\d+)/);
        if (!m || seen.has(m[1])) return;
        seen.add(m[1]);
        out.push({id: m[1], text: a.innerText || ""});
      });
      return out;
    }"""

    async def fetch(self) -> list[Listing]:
        cookie = self._load_cookie()
        if not cookie:
            log.info(
                "fb_marketplace skipped: set FB_USER_COOKIE, or put the cookie "
                "string in ~/.porsche_fb_cookie, to enable this scraper. Copy it "
                "from a logged-in facebook.com request in your browser devtools."
            )
            return []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.warning("fb_marketplace: playwright not installed")
            return []

        ua = os.environ.get(
            "FB_USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        cards: dict[str, str] = {}
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(user_agent=ua, locale="en-US")
                await ctx.add_cookies(self._cookie_pairs(cookie))
                page = await ctx.new_page()
                from urllib.parse import quote
                for q in self.QUERIES:
                    # Keep the URL to just the query — adding maxPrice/sortBy
                    # made the search return nothing. Price and year are filtered
                    # in code from the card text instead.
                    url = ("https://www.facebook.com/marketplace/search/"
                           f"?query={quote(q)}")
                    try:
                        await page.goto(url, wait_until="domcontentloaded",
                                        timeout=45000)
                        await page.wait_for_timeout(5000)
                        for _ in range(self.SCROLLS):
                            await page.evaluate(
                                "window.scrollTo(0, document.body.scrollHeight)")
                            await page.wait_for_timeout(2200)
                        for row in await page.evaluate(self._JS_EXTRACT):
                            cards.setdefault(row["id"], row["text"])
                    except Exception as exc:  # noqa: BLE001
                        log.warning("fb_marketplace query %r failed: %s", q, exc)
                await browser.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("fb_marketplace browser session failed: %s", exc)
            return []

        listings = []
        for lid, text in cards.items():
            li = _card_to_listing(lid, text)
            if li is not None:
                listings.append(li)
        log.info("fb_marketplace: %d cards -> %d porsche cars", len(cards),
                 len(listings))
        return listings


# Facebook's Marketplace JSON shape (confirmed live 2026-08-14). Each car is a
# GroupCommerceProductItem, and the fields sit in the object in this order:
#   id ... primary_listing_photo ... listing_price ... location ... TITLE ... miles
# The old `"listing_id":"..."` anchor is GONE — FB stopped emitting that key,
# which is why the previous parser silently returned zero.
#
# Anchor on the TITLE, not the id: FB's normalized Relay store repeats each item
# id (once with full data, once or more as a bare reference), so slicing between
# id anchors collapses most items to empty. The title appears exactly once per
# real listing, so it is the reliable anchor. Read a window behind it for the id,
# price and location, and a small window ahead for mileage.
_FB_TITLE_RE = re.compile(
    r'"marketplace_listing_title":"([^"\\]*(?:\\.[^"\\]*)*)"')
_FB_ID_RE = re.compile(r'"__typename":"GroupCommerceProductItem","id":"(\d+)"')
_FB_LOOKBEHIND = 2500
_FB_LOOKAHEAD = 600


def _fb_unescape(s: str) -> str:
    if not s:
        return ""
    try:
        return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def parse_fb_html(html: str) -> Iterable[Listing]:
    """Parse FB Marketplace's embedded Relay JSON. Best-effort, current as of
    2026-08-14.

    Each listing is a `GroupCommerceProductItem` block:

        "__typename":"GroupCommerceProductItem","id":"<LISTING_ID>",
          ...,"listing_price":{...,"amount":"40000.00"},
          ...,"location":{...,"display_name":"Inman, South Carolina"},
          ...,"marketplace_listing_title":"2016 Porsche Cayman ...",
          ...,"custom_sub_titles_with_rendering_flags":[{"subtitle":"62K miles"}]

    Anchor on the item id, then read the slice up to the next item.
    """
    seen: set[str] = set()
    for m in _FB_TITLE_RE.finditer(html):
        title = _fb_unescape(m.group(1))
        low = title.lower()
        if "porsche" not in low:
            continue
        if any(em in low for em in ("panamera", "macan")):
            continue

        behind = html[max(0, m.start() - _FB_LOOKBEHIND):m.start()]
        ahead = html[m.end():m.end() + _FB_LOOKAHEAD]

        # The item id, price and location all sit BEFORE the title in the block,
        # so take the nearest (last) match in the lookbehind window.
        ids = _FB_ID_RE.findall(behind)
        lid = ids[-1] if ids else None
        if not lid or lid in seen:
            continue
        seen.add(lid)

        prices = re.findall(r'"listing_price":\{[^}]*?"amount":"([\d.]+)"', behind)
        locs = re.findall(r'"display_name":"([^"]+)"', behind)
        photos = re.findall(r'"image":\{"uri":"([^"]+)"', behind)
        # Mileage ("62K miles") sits just AFTER the title.
        miles_m = (
            re.search(r'"subtitle":"([\d,.]+\s*[Kk]?\s*miles)"', ahead)
            or re.search(r'([\d,]+\s*[Kk]?)\s*miles', ahead)
        )

        price_val = parse_price(prices[-1]) if prices else None
        mileage_val = parse_miles(miles_m.group(1)) if miles_m else parse_miles(title)
        status = infer_title_status(title)
        listing = Listing(
            source="fb_marketplace",
            source_url=f"https://www.facebook.com/marketplace/item/{lid}/",
            listing_id=lid,
            title=title,
            year=parse_year(title),
            mileage=mileage_val,
            price_usd=price_val,
            location=_fb_unescape(locs[-1]) if locs else None,
            photo_url=_fb_unescape(photos[-1]) if photos else None,
            title_status=status,
            seller_type="private",
        )
        listing.drivable = infer_drivable(title, status)
        yield listing


# Marketplace search returns Porsche CARS mixed with PARTS (wheels, doors,
# emblems, coils, bumpers) and other makes. Parts are the noise to drop.
_FB_PARTS_RE = re.compile(
    r"\b(wheel|wheels|tire|tires|rim|rims|door|doors|bumper|emblem|badge|coil|"
    r"coils|seat|seats|interior|hood|fender|mirror|headlight|taillight|engine|"
    r"transmission|part|parts|oem|steering|exhaust|spoiler|hubcap|manual|book|"
    r"key|fob|cover|mat|mats|shifter|caliper|brake|rotor|bra\b|nose bra)\b",
    re.I)
_FB_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
_FB_PRICE_LINE_RE = re.compile(r"\$([\d,]+)")
_FB_LOC_LINE_RE = re.compile(r"^[A-Za-z .'-]+,\s*[A-Z]{2}$")
_FB_MILES_RE = re.compile(r"([\d,.]+\s*[Kk]?)\s*miles", re.I)


def _card_to_listing(lid: str, text: str):
    """Turn one Marketplace card's visible text into a Listing, or None.

    Card text is newline-separated: one or two prices, the title, the location,
    and sometimes a mileage subtitle. Keeps only actual Porsche cars — a title
    with a Porsche model AND a plausible model year, and NOT a parts listing.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    joined = " ".join(lines)
    low = joined.lower()
    if "porsche" not in low:
        return None
    if any(em in low for em in ("panamera", "macan")):
        return None
    if _FB_PARTS_RE.search(low):
        return None

    # The title is the line that names a year and Porsche; parts/non-cars fail.
    title = next((ln for ln in lines
                  if _FB_YEAR_RE.search(ln) and "porsche" in ln.lower()), None)
    if not title:
        return None

    prices = _FB_PRICE_LINE_RE.findall(joined)
    price_val = parse_price(prices[0]) if prices else None
    location = next((ln for ln in lines if _FB_LOC_LINE_RE.match(ln)), None)
    miles_m = _FB_MILES_RE.search(joined)

    status = infer_title_status(title)
    listing = Listing(
        source="fb_marketplace",
        source_url=f"https://www.facebook.com/marketplace/item/{lid}/",
        listing_id=lid,
        title=title,
        year=parse_year(title),
        mileage=parse_miles(miles_m.group(1)) if miles_m else parse_miles(title),
        price_usd=price_val,
        location=location,
        title_status=status,
        seller_type="private",
    )
    listing.drivable = infer_drivable(title, status)
    return listing


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
