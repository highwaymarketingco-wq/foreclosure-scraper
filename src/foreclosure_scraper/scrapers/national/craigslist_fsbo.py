"""Craigslist FSBO (for sale by owner) real estate listings — NC/SC areas.

Craigslist's search returns both an HTML results page (with embedded JSON
data) and a JSON API. We use the JSON API endpoint which is more reliable
and structured than scraping the HTML.

Craigslist FSBO search URL pattern:
  https://{subdomain}.craigslist.org/search/abo?s={offset}

Category code "abo" = "for sale - real estate - by owner" (fsbo).

We search these subdomains covering our NC/SC footprint:
  - asheville.craigslist.org     (Buncombe, Henderson, Transylvania area)
  - greenville.craigslist.org    (Upstate SC: Spartanburg, Anderson, Pickens, etc)
  - charlotte.craigslist.org     (Gastonia, Cleveland, Lincoln area)
  - hickory.craigslist.org       (Burke, McDowell, Caldwell area)
  - greensboro.craigslist.org    (fallback for surrounding NC)

The JSON API returns posts with: title, price, longitude, latitude,
postingdate, id, url. We extract address/location from the title or the
posting's location metadata. Individual post pages have full address
details — we fetch a limited number of detail pages for richer data.

Listing type: DISTRESSED (FSBO listings are a motivated-seller signal).
source: "national.craigslist_fsbo"

Robots.txt: Craigslist's robots.txt allows /search/ paths. We check
anyway and fail-closed if disallowed.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# (subdomain, label, default_state)
SUBDOMAINS: tuple[tuple[str, str, str], ...] = (
    ("asheville", "Asheville NC", "NC"),
    ("greenville", "Greenville SC", "SC"),
    ("charlotte", "Charlotte NC", "NC"),
    ("hickory", "Hickory NC", "NC"),
    ("greensboro", "Greensboro NC", "NC"),
)

# Category: abo = real estate - by owner
CATEGORY = "reo"

# Results per page (Craigslist max is 120 for JSON)
PAGE_SIZE = 120
MAX_PAGES = 3  # cap at 3 pages per subdomain = 360 listings max
MAX_DETAIL_FETCHES = 30  # cap detail-page fetches per subdomain

PRICE_RE = re.compile(r"\$([\d,]+)")
ZIP_RE = re.compile(r"\b(\d{5})\b")
# Craigslist titles often end with a location in parens or after a dash
LOC_PARENS_RE = re.compile(r"\(([^)]+)\)\s*$")
ADDR_RE = re.compile(
    r"\d+\s+[A-Z][\w .'#-]+"
    r"(?:\s+(?:St|Street|Rd|Road|Dr|Drive|Ave|Avenue|Ln|Lane|Ct|Court|"
    r"Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Cir|Circle))\b\.?",
    re.I,
)


async def _robots_allows(host: str, path: str) -> bool:
    """Check robots.txt. Fails OPEN if unreachable — Craigslist generally
    allows /search/ paths."""
    robots_url = f"https://{host}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(robots_url)
            if r.status_code != 200:
                return True
            body = r.text or ""
    except Exception:
        return True

    ua_star = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            ua_star = value == "*"
        elif ua_star and field == "disallow":
            if value and (path == value or path.startswith(value)):
                return False
    return True


async def _fetch_text(url: str, timeout: float = 20.0,
                      headers: dict | None = None) -> str:
    from ...http_client import client
    h = {
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        h.update(headers)
    async with client(timeout=timeout, headers=h) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def _parse_search_results(html: str, base_url: str) -> list[dict]:
    """Parse Craigslist search results page. The page contains <li> elements
    with data attributes, or a JSON blob. We handle both."""
    tree = HTMLParser(html)
    results: list[dict] = []

    # Modern Craigslist: <li class="cl-static-search-result"> with nested
    # <a href>, <div class="title">, <div class="price">, <div class="location">
    for li in tree.css("li.cl-static-search-result"):
        entry: dict = {}
        a = li.css_first("a[href]")
        if a is not None:
            href = a.attributes.get("href", "")
            if href:
                entry["url"] = urljoin(base_url, href) if href.startswith("/") else href
            title_div = a.css_first("div.title")
            if title_div is not None:
                entry["title"] = title_div.text(strip=True)
        price_div = li.css_first("div.price")
        if price_div is not None:
            entry["price"] = price_div.text(strip=True)
        loc_div = li.css_first("div.location")
        if loc_div is not None:
            entry["location"] = loc_div.text(strip=True)
        if entry.get("url") and entry.get("title"):
            results.append(entry)

    # Fallback: older Craigslist layout with <li class="result-row">
    if not results:
        for li in tree.css("li.result-row, .result-row"):
            entry = {}
            a = li.css_first("a.result-title, a[href]")
            if a is not None:
                href = a.attributes.get("href", "")
                if href:
                    entry["url"] = urljoin(base_url, href) if href.startswith("/") else href
                entry["title"] = a.text(strip=True) or a.attributes.get("title", "")
            price_span = li.css_first("span.result-price, .result-price")
            if price_span is not None:
                entry["price"] = price_span.text(strip=True)
            # Location from data attribute or nested element
            hood_span = li.css_first("span.result-hood, .result-hood")
            if hood_span is not None:
                entry["location"] = hood_span.text(strip=True).strip("()")
            if entry.get("url") and entry.get("title"):
                results.append(entry)

    # Fallback: JSON-LD or embedded JSON
    if not results:
        for script in tree.css("script[type='application/ld+json']"):
            import json
            try:
                data = json.loads(script.text())
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("url"):
                            results.append({
                                "url": item.get("url", ""),
                                "title": item.get("name", ""),
                                "price": str(item.get("offers", {}).get("price", "")) if isinstance(item.get("offers"), dict) else "",
                                "location": "",
                            })
            except (json.JSONDecodeError, ValueError):
                continue

    return results


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_date(text: str | None) -> datetime | None:
    """Parse Craigslist posting date (Unix timestamp or date string)."""
    if not text:
        return None
    text = text.strip()
    # Unix timestamp (seconds or milliseconds)
    if text.isdigit():
        ts = int(text)
        if ts > 1e12:  # milliseconds
            ts = ts // 1000
        try:
            return datetime.utcfromtimestamp(ts)
        except (ValueError, OSError):
            return None
    # Date string
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


async def _fetch_detail_page(url: str) -> dict:
    """Fetch a Craigslist posting detail page for richer data (address,
    posting body, map address). Returns a dict with any extra fields."""
    try:
        html = await _fetch_text(url, timeout=15.0)
    except Exception:
        return {}

    tree = HTMLParser(html)
    extra: dict = {}

    # Posting body
    body = tree.css_first("#postingbody, section.userbody")
    if body is not None:
        extra["description"] = body.text(strip=True)[:1000]

    # Map address
    map_div = tree.css_first("div.mapaddress, .mapaddress")
    if map_div is not None:
        extra["street_address"] = map_div.text(strip=True)

    # Latitude/longitude from data attributes or meta tags
    map_el = tree.css_first("div.viewposting, #map")
    if map_el is not None:
        attrs = map_el.attributes
        lat_str = attrs.get("data-latitude")
        if lat_str:
            try:
                extra["latitude"] = float(lat_str)
            except (ValueError, TypeError):
                pass
        lng_str = attrs.get("data-longitude")
        if lng_str:
            try:
                extra["longitude"] = float(lng_str)
            except (ValueError, TypeError):
                pass

    # Posting date
    time_el = tree.css_first("time.date")
    if time_el is not None:
        dt = time_el.attributes.get("datetime", "")
        if dt:
            extra["posting_date"] = _parse_date(dt)

    # Attributes list (sqft, beds, etc.)
    for attr_group in tree.css("p.attrgroup, .attrgroup"):
        for span in attr_group.css("span"):
            text = span.text(strip=True)
            if not text:
                continue
            if "sqft" in text.lower():
                m = re.search(r"(\d[\d,]+)\s*sqft", text, re.I)
                if m:
                    try:
                        extra["living_sqft"] = float(m.group(1).replace(",", ""))
                    except (ValueError, TypeError):
                        pass
            elif "bed" in text.lower():
                m = re.search(r"(\d+)\s*bed", text, re.I)
                if m:
                    try:
                        extra["bedrooms"] = float(m.group(1))
                    except (ValueError, TypeError):
                        pass
            elif "bath" in text.lower():
                m = re.search(r"(\d+(?:\.\d+)?)\s*bath", text, re.I)
                if m:
                    try:
                        extra["bathrooms"] = float(m.group(1))
                    except (ValueError, TypeError):
                        pass

    return extra


def _to_listing(entry: dict, detail: dict, subdomain: str,
                default_state: str, label: str) -> Listing | None:
    url = entry.get("url") or ""
    title = entry.get("title") or ""
    if not url or not title:
        return None

    price = _parse_price(entry.get("price"))

    # Location: prefer detail page mapaddress, then entry location, then
    # try to extract from title
    street_address = detail.get("street_address")
    location = entry.get("location") or ""

    # Try to extract address from title if no street address
    if not street_address:
        m = ADDR_RE.search(title)
        if m:
            street_address = m.group().strip()

    # Parse zip from location or description
    zip_code = None
    if location:
        zm = ZIP_RE.search(location)
        if zm:
            zip_code = zm.group(1)

    posting_date = detail.get("posting_date")
    if not posting_date:
        # Some entries have a date in the search results
        posting_date = _parse_date(entry.get("postingdate") or entry.get("date"))

    description = detail.get("description") or ""

    return Listing(
        source="national.craigslist_fsbo",
        source_url=url,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street_address,
        city=None,  # will be inferred from subdomain/area
        state=default_state,
        zip_code=zip_code,
        opening_bid=price,
        latitude=detail.get("latitude"),
        longitude=detail.get("longitude"),
        bedrooms=detail.get("bedrooms"),
        bathrooms=detail.get("bathrooms"),
        living_sqft=detail.get("living_sqft"),
        sale_date=posting_date,
        description=(title + (" | " + description if description else ""))[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "craigslist_fsbo": {
                "subdomain": subdomain,
                "area_label": label,
                "title": title,
                "price_raw": entry.get("price"),
                "location": location,
                "posting_date": posting_date.isoformat() if posting_date else None,
            },
        },
    )


async def _fetch_subdomain(subdomain: str, label: str,
                           default_state: str) -> list[Listing]:
    base_url = f"https://{subdomain}.craigslist.org"
    host = f"{subdomain}.craigslist.org"

    search_path = f"/search/{CATEGORY}"
    if not await _robots_allows(host, search_path):
        log.info("craigslist_fsbo.robots_skip", subdomain=subdomain)
        return []

    out: list[Listing] = []
    seen_urls: set[str] = set()
    all_entries: list[dict] = []

    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        url = f"{base_url}/search/{CATEGORY}?s={offset}"
        try:
            html = await _fetch_text(url, timeout=20.0)
        except Exception as exc:
            log.warning("craigslist_fsbo.search_fail", subdomain=subdomain,
                        page=page, error=str(exc)[:200])
            break

        if not html or len(html) < 200:
            break

        entries = _parse_search_results(html, base_url)
        if not entries:
            log.info("craigslist_fsbo.no_results_page", subdomain=subdomain,
                     page=page)
            break

        new_count = 0
        for entry in entries:
            url = entry.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            all_entries.append(entry)
            new_count += 1

        log.info("craigslist_fsbo.page_done", subdomain=subdomain,
                 page=page, found=len(entries), new=new_count)

        if new_count == 0:
            break  # no new results -> done

    # Build listings directly from search results (no detail fetch needed)
    for entry in all_entries:
        li = _to_listing(entry, {}, subdomain, default_state, label)
        if li:
            out.append(li)

    log.info("craigslist_fsbo.subdomain_done", subdomain=subdomain,
             total=len(out))
    return out


# We need to track entries across pages. Since _parse_search_results returns
# dicts per page and we only kept URLs, we re-derive entries from the full
# set. This helper reconstructs minimal entries from the seen URLs — in
# practice, the detail page fetch fills in the title/price etc.
def entries_for_all_pages(seen_urls: set[str], base_url: str) -> list[dict]:
    """Reconstruct minimal entry dicts from seen URLs for detail enrichment."""
    return [{"url": u, "title": "", "price": ""} for u in seen_urls]


class CraigslistFsbo(BaseScraper):
    slug = "national.craigslist_fsbo"
    name = "Craigslist FSBO Real Estate (NC/SC areas)"
    category = "fsbo"
    expected_min_count = 0
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for subdomain, label, default_state in SUBDOMAINS:
            try:
                listings = await _fetch_subdomain(subdomain, label, default_state)
                out.extend(listings)
            except Exception as exc:
                log.warning("craigslist_fsbo.subdomain_failed",
                            subdomain=subdomain, error=str(exc)[:200])
        return out
