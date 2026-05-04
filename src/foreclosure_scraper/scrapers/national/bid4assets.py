"""Bid4Assets — county tax sale auctions via Scrapling stealth (no Apify).

Bid4Assets uses ColdFusion CFM with session cookies. Direct httpx returns
the empty search shell. Scrapling renders the search page for each state
and we extract auction cards from the DOM.
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
    ("NC", "https://www.bid4assets.com/storefront/index.cfm?searchstate=NC&searchprop=Real+Estate"),
    ("SC", "https://www.bid4assets.com/storefront/index.cfm?searchstate=SC&searchprop=Real+Estate"),
)


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector("a[href*='auction'], .auction, table tr",
                                         timeout=30000)
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
        log.warning("bid4assets.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)

    for a in tree.css("a[href*='auction']"):
        href = a.attributes.get("href", "")
        if not href or "auction" not in href.lower():
            continue
        if href.startswith("/"):
            href = f"https://www.bid4assets.com{href}"
        if href in seen:
            continue
        seen.add(href)

        title = a.text(strip=True) or ""
        if not title or len(title) < 10:
            continue

        m = re.search(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+County\b", title)
        county = m.group(1) if m else None

        addr_m = re.search(
            r"\d+\s+[A-Z][\w .']+(?:Road|Rd|Street|St|Drive|Dr|Avenue|Ave|Lane|Ln|Way|Court|Ct|Place|Pl|Boulevard|Blvd)",
            title, re.I,
        )

        out.append(
            Listing(
                source="national.bid4assets",
                source_url=href,
                listing_type=ListingType.AUCTION,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county=county,
                street_address=addr_m.group() if addr_m else None,
                description=f"Bid4Assets {state} auction — {title[:200]}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"bid4assets": {"title": title}},
            )
        )

    return out


class Bid4Assets(BaseScraper):
    slug = "national.bid4assets"
    name = "Bid4Assets"
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
                log.info("bid4assets.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("bid4assets.state_failed", state=state, error=str(exc)[:200])
        return out
