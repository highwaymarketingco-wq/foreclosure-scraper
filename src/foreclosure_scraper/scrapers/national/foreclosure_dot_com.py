"""Foreclosure.com via Scrapling stealth (no Apify, no paid).

Scrapes their public state-listing pages directly. Foreclosure.com requires
a paid subscription for full property details, but the public preview
listing pages show address + city + zip + status.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.foreclosure.com/listings/north-carolina/"),
    ("SC", "https://www.foreclosure.com/listings/south-carolina/"),
)


def _ltype(text: str) -> ListingType:
    t = (text or "").lower()
    if "auction" in t:
        return ListingType.AUCTION
    if "reo" in t or "bank" in t:
        return ListingType.REO
    if "pre" in t:
        return ListingType.LIS_PENDENS
    return ListingType.FORECLOSURE_SALE


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[class*='listing'], [class*='property'], a[href*='/listing/']",
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
        log.warning("foreclosure_dot_com.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)
    for card in tree.css("[class*='listing-card'], [class*='property-card'], article, tr"):
        try:
            addr_node = card.css_first("[class*='address']") or card.css_first("td")
            addr = addr_node.text(strip=True) if addr_node else ""
            if not addr or len(addr) < 8:
                continue
            m = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?", addr)
            if not m:
                continue
            street, city, st, z = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
            if st != state:
                continue
            link_node = card.css_first("a[href*='/listing/']") or card.css_first("a[href]")
            link = (link_node.attributes.get("href", "") if link_node else "") or url
            if link and not link.startswith("http"):
                link = f"https://www.foreclosure.com{link}"
            if link in seen:
                continue
            seen.add(link)
            status_node = card.css_first("[class*='status']")
            status = status_node.text(strip=True) if status_node else ""
            out.append(
                Listing(
                    source="national.foreclosure_dot_com",
                    source_url=link,
                    listing_type=_ltype(status),
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=street, city=city, state=st, zip_code=z,
                    auction_status=status or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"foreclosure_dot_com": {"status": status}},
                )
            )
        except Exception:
            continue
    return out


class ForeclosureDotCom(BaseScraper):
    slug = "national.foreclosure_dot_com"
    name = "Foreclosure.com"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state, url in URLS:
            try:
                listings = await _fetch_state(state, url)
                out.extend(listings)
                log.info("foreclosure_dot_com.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("foreclosure_dot_com.state_failed", state=state, error=str(exc)[:200])
        return out
