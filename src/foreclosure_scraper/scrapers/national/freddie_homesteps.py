"""Freddie Mac HomeSteps REO inventory.

The /listing/search page is a SPA. Renders via Scrapling's StealthyFetcher.
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
    ("NC", "https://www.homesteps.com/listing/search?state=NC"),
    ("SC", "https://www.homesteps.com/listing/search?state=SC"),
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
    if "land" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _make_listing(addr: str, city: str | None, state: str, zip_code: str | None,
                  price: str, beds: str | None, baths: str | None, sqft: str | None,
                  kind_text: str | None, link: str | None) -> Listing | None:
    if not addr or len(addr) < 4:
        return None

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

    price_val = None
    if price:
        pm = re.search(r"\$?([\d,]+)", str(price))
        if pm:
            try:
                price_val = float(pm.group(1).replace(",", ""))
            except ValueError:
                pass

    return Listing(
        source="national.freddie_homesteps",
        source_url=link or "https://www.homesteps.com/",
        listing_type=ListingType.REO,
        property_kind=_kind(kind_text),
        street_address=addr,
        city=city,
        state=state,
        zip_code=zip_code,
        opening_bid=price_val,
        bedrooms=_num(beds),
        bathrooms=_num(baths),
        living_sqft=_num(sqft),
        description=f"Freddie Mac HomeSteps REO. {kind_text or ''}".strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"homesteps": {"kind_text": kind_text}},
    )


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("freddie.scrapling_missing")
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[class*='card'], [class*='listing'], a[href*='/listing/'], .property",
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
        log.warning("freddie.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen: set[str] = set()

    # Try embedded JSON state
    for marker in ("window.__INITIAL_STATE__", "window.__APP_STATE__", "__NEXT_DATA__"):
        if marker in html:
            blob_m = re.search(re.escape(marker) + r"\s*=\s*(\{.+?\})\s*;\s*</?", html, re.S)
            if blob_m:
                try:
                    data = json.loads(blob_m.group(1))
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
                        addr = item.get("address") or item.get("streetAddress") or ""
                        if isinstance(addr, dict):
                            addr = addr.get("line1") or addr.get("streetAddress") or ""
                        if not addr or addr in seen:
                            continue
                        seen.add(addr)
                        link = item.get("url") or item.get("propertyUrl")
                        if link and not link.startswith("http"):
                            link = f"https://www.homesteps.com{link}"
                        li = _make_listing(
                            addr, item.get("city"), state,
                            item.get("zip") or item.get("zipCode"),
                            str(item.get("listPrice") or item.get("price") or ""),
                            str(item.get("beds") or item.get("bedrooms") or ""),
                            str(item.get("baths") or item.get("bathrooms") or ""),
                            str(item.get("sqft") or item.get("livingArea") or ""),
                            item.get("propertyType") or item.get("homeType"),
                            link,
                        )
                        if li:
                            out.append(li)
                except (ValueError, KeyError):
                    pass

    # Fallback: parse rendered HTML
    if not out:
        tree = HTMLParser(html)
        for card in tree.css("[class*='card'], [class*='listing-tile'], .property-card, article"):
            try:
                addr_node = card.css_first("[class*='address']")
                price_node = card.css_first("[class*='price']")
                link_node = card.css_first("a[href]")
                addr = addr_node.text(strip=True) if addr_node else ""
                if not addr or addr in seen:
                    continue
                seen.add(addr)
                # Parse "Street, City, ST ZIP"
                m = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?", addr)
                if not m:
                    continue
                street, city, st, z = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
                if st != state:
                    continue
                price = price_node.text(strip=True) if price_node else ""
                link = link_node.attributes.get("href") if link_node else None
                if link and not link.startswith("http"):
                    link = f"https://www.homesteps.com{link}"
                li = _make_listing(street, city, st, z, price, None, None, None, None, link)
                if li:
                    out.append(li)
            except Exception:
                continue

    return out


class FreddieHomeSteps(BaseScraper):
    slug = "national.freddie_homesteps"
    name = "Freddie Mac HomeSteps (REO)"
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
                log.info("freddie.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("freddie.state_failed", state=state, error=str(exc)[:200])
        return out
