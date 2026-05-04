"""Hubzu auction REO via Scrapling stealth (no Apify)."""
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
    ("NC", "https://www.hubzu.com/properties?location=north%20carolina"),
    ("SC", "https://www.hubzu.com/properties?location=south%20carolina"),
)


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[class*='property'], [class*='listing'], a[href*='/property/'], a[href*='/home/']",
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
        log.warning("hubzu.fetch_fail", state=state, error=str(exc)[:200])
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
            link_node = (card.css_first("a[href*='/property/']") or
                         card.css_first("a[href*='/home/']") or
                         card.css_first("a[href]"))
            link = (link_node.attributes.get("href", "") if link_node else "") or url
            if link and not link.startswith("http"):
                link = f"https://www.hubzu.com{link}"
            if link in seen:
                continue
            seen.add(link)

            addr_node = card.css_first("[class*='address']")
            price_node = card.css_first("[class*='price']")
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
                    source="national.hubzu",
                    source_url=link,
                    listing_type=ListingType.AUCTION,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=street, city=city, state=st, zip_code=z,
                    opening_bid=price,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"hubzu": {}},
                )
            )
        except Exception:
            continue
    return out


class Hubzu(BaseScraper):
    slug = "national.hubzu"
    name = "Hubzu (REO Auction)"
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
                log.info("hubzu.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("hubzu.state_failed", state=state, error=str(exc)[:200])
        return out
