"""Xome auctions via Scrapling stealth (no Apify).

REO + foreclosure auctions. SPA. Scrapling stealth handles rendering.
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
    # Xome lists by city, not state. Hit our footprint metros + auctions page.
    ("NC", "https://www.xome.com/auctions/NC"),
    ("SC", "https://www.xome.com/auctions/SC"),
    ("NC", "https://www.xome.com/realestate/NC/Charlotte"),
    ("NC", "https://www.xome.com/realestate/NC/Asheville"),
    ("SC", "https://www.xome.com/realestate/SC/Greenville"),
    ("SC", "https://www.xome.com/realestate/SC/Spartanburg"),
)


def _kind(label: str | None) -> PropertyKind:
    if not label:
        return PropertyKind.UNKNOWN
    s = label.lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s:
        return PropertyKind.MULTI_FAMILY
    if "mobile" in s:
        return PropertyKind.MOBILE
    if "land" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[class*='property-card'], [class*='listing'], a[href*='/listing/'], article",
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
        log.warning("xome.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)

    for card in tree.css("[class*='property-card'], [class*='listing-card'], article"):
        try:
            link_node = card.css_first("a[href*='/listing/']") or card.css_first("a[href]")
            link = (link_node.attributes.get("href", "") if link_node else "") or url
            if link and not link.startswith("http"):
                link = f"https://www.xome.com{link}"
            if link in seen:
                continue
            seen.add(link)

            addr_node = card.css_first("[class*='address']")
            price_node = card.css_first("[class*='price']")
            kind_node = card.css_first("[class*='type']")

            addr = addr_node.text(strip=True) if addr_node else ""
            if not addr or len(addr) < 8:
                continue
            m = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?", addr)
            if not m:
                continue
            street, city, st, z = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
            if st != state:
                continue

            price = None
            if price_node:
                pm = re.search(r"\$([\d,]+)", price_node.text(strip=True))
                if pm:
                    try:
                        price = float(pm.group(1).replace(",", ""))
                    except ValueError:
                        pass

            out.append(
                Listing(
                    source="national.xome",
                    source_url=link,
                    listing_type=ListingType.AUCTION,
                    property_kind=_kind(kind_node.text(strip=True) if kind_node else None),
                    street_address=street,
                    city=city,
                    state=st,
                    zip_code=z,
                    opening_bid=price,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"xome": {}},
                )
            )
        except Exception:
            continue

    return out


class Xome(BaseScraper):
    slug = "national.xome"
    name = "Xome"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state, url in URLS:
            try:
                listings = await _fetch_state(state, url)
                out.extend(listings)
                log.info("xome.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("xome.state_failed", state=state, error=str(exc)[:200])
        return out
