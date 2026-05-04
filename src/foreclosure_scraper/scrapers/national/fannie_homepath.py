"""Fannie Mae HomePath REO inventory.

The site is a React SPA — direct HTTP returns the empty shell. We render
with Scrapling's StealthyFetcher (camoufox/Playwright stealth) and extract
property cards from the rendered DOM.

Free to scrape, no auth required. Filtered to NC + SC.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.homepath.com/listing-search?state=NC&showOnly=All"),
    ("SC", "https://www.homepath.com/listing-search?state=SC&showOnly=All"),
)


def _kind(label: str | None) -> PropertyKind:
    if not label:
        return PropertyKind.UNKNOWN
    s = label.lower()
    if "single" in s or "detached" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _make_listing(addr_text: str, price_text: str, beds: str | None, baths: str | None,
                  sqft: str | None, kind_text: str | None, link: str | None,
                  state_filter: str) -> Listing | None:
    m = re.match(
        r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?",
        addr_text.strip(),
    )
    if not m:
        return None
    street, city, state, zip_code = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
    if state != state_filter:
        return None

    price = None
    if price_text:
        pm = re.search(r"\$?([\d,]+)", str(price_text))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                pass

    def _num(s: str | None) -> float | None:
        if not s:
            return None
        m = re.search(r"[\d.]+", str(s).replace(",", ""))
        if m:
            try:
                return float(m.group())
            except ValueError:
                return None
        return None

    return Listing(
        source="national.fannie_homepath",
        source_url=link or "https://www.homepath.com/",
        listing_type=ListingType.REO,
        property_kind=_kind(kind_text),
        street_address=street,
        city=city,
        state=state,
        zip_code=zip_code,
        opening_bid=price,
        bedrooms=_num(beds),
        bathrooms=_num(baths),
        living_sqft=_num(sqft),
        description=f"Fannie Mae HomePath REO. {kind_text or ''}".strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"fannie_homepath": {
            "kind_text": kind_text,
            "price_text": price_text,
        }},
    )


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("fannie.scrapling_missing")
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[data-testid*='listing'], a[href*='/property/'], .listing-card, .property-card, [class*='card']",
                timeout=30000,
            )
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("fannie.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen_addrs: set[str] = set()

    # Try parsing __NEXT_DATA__ first (Next.js SSR JSON)
    nd = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.S
    )
    if nd:
        try:
            data = json.loads(nd.group(1))
            def _walk(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k.lower() in ("listings", "properties", "results", "items") and isinstance(v, list):
                            yield from v
                        else:
                            yield from _walk(v)
                elif isinstance(obj, list):
                    for it in obj:
                        yield from _walk(it)

            for item in _walk(data):
                if not isinstance(item, dict):
                    continue
                addr = (item.get("address") or item.get("fullAddress")
                        or item.get("formattedAddress") or "")
                if isinstance(addr, dict):
                    parts = [addr.get("streetAddress") or addr.get("line1"),
                             addr.get("city"), addr.get("state"),
                             addr.get("postalCode") or addr.get("zip")]
                    addr = ", ".join(p for p in parts if p)
                if not addr or len(addr) < 8 or addr in seen_addrs:
                    continue
                seen_addrs.add(addr)
                price = item.get("listPrice") or item.get("price")
                beds = item.get("beds") or item.get("bedrooms")
                baths = item.get("baths") or item.get("bathrooms")
                sqft = item.get("sqft") or item.get("livingArea")
                kind = item.get("propertyType") or item.get("homeType") or ""
                link = item.get("url") or item.get("href")
                if link and not link.startswith("http"):
                    link = f"https://www.homepath.com{link}"
                li = _make_listing(addr, str(price or ""), str(beds or ""),
                                   str(baths or ""), str(sqft or ""), kind, link, state)
                if li:
                    out.append(li)
        except (ValueError, KeyError):
            pass

    # Fallback: parse rendered HTML cards
    if not out:
        tree = HTMLParser(html)
        for card in tree.css("[data-testid*='listing'], .listing-card, .property-card, article, [class*='card']"):
            try:
                addr_node = card.css_first("[class*='address'], [data-testid*='address']")
                price_node = card.css_first("[class*='price'], [data-testid*='price']")
                kind_node = card.css_first("[class*='type'], [data-testid*='type']")
                link_node = card.css_first("a[href*='/property/']") or card.css_first("a[href]")
                addr = addr_node.text(strip=True) if addr_node else ""
                price = price_node.text(strip=True) if price_node else ""
                kind = kind_node.text(strip=True) if kind_node else ""
                link = (link_node.attributes.get("href") if link_node else None)
                if link and not link.startswith("http"):
                    link = f"https://www.homepath.com{link}"
                if addr in seen_addrs:
                    continue
                seen_addrs.add(addr)
                li = _make_listing(addr, price, None, None, None, kind, link, state)
                if li:
                    out.append(li)
            except Exception:
                continue

    return out


class FannieHomePath(BaseScraper):
    slug = "national.fannie_homepath"
    name = "Fannie Mae HomePath (REO)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state, url in URLS:
            try:
                listings = await _fetch_state(state, url)
                out.extend(listings)
                log.info("fannie.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("fannie.state_failed", state=state, error=str(exc)[:200])
        return out
