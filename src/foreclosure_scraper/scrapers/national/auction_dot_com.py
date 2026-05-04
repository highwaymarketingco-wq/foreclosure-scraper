"""Auction.com via Scrapling stealth (no Apify, no paid).

Auction.com is a major foreclosure auction site. SPA-rendered, no public
JSON endpoint. Scrapling's StealthyFetcher renders the search page, then
we parse property cards from the DOM.

Free, no auth required.
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
    ("NC", "https://www.auction.com/residential/nc/"),
    ("SC", "https://www.auction.com/residential/sc/"),
)


def _kind(raw: str | None) -> PropertyKind:
    if not raw:
        return PropertyKind.UNKNOWN
    s = str(raw).lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


def _ltype_from_status(s: str) -> ListingType:
    s = (s or "").lower()
    if "auction" in s:
        return ListingType.AUCTION
    if "reo" in s or "bank" in s:
        return ListingType.REO
    if "fore" in s:
        return ListingType.FORECLOSURE_SALE
    return ListingType.AUCTION


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("auction_dot_com.scrapling_missing")
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[data-elm-id*='property'], [data-testid*='property'], "
                ".pc-asset-list, a[href*='/details/']",
                timeout=30000,
            )
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2500)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("auction_dot_com.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)

    cards = tree.css(
        "[data-elm-id*='property'], [data-testid*='property'], "
        ".asset-card, [class*='asset'], article"
    )
    for card in cards:
        try:
            link_node = card.css_first("a[href*='/details/']") or card.css_first("a[href]")
            if not link_node:
                continue
            link = link_node.attributes.get("href", "")
            if link and not link.startswith("http"):
                link = f"https://www.auction.com{link}"
            if link in seen:
                continue
            seen.add(link)

            addr_node = card.css_first("[class*='address'], [data-testid*='address']")
            price_node = card.css_first("[class*='price'], [data-testid*='price']")
            status_node = card.css_first("[class*='status'], [class*='auction']")
            kind_node = card.css_first("[class*='type']")

            addr = addr_node.text(strip=True) if addr_node else ""
            price_text = price_node.text(strip=True) if price_node else ""
            status_text = status_node.text(strip=True) if status_node else ""
            kind_text = kind_node.text(strip=True) if kind_node else ""

            if not addr or len(addr) < 8:
                continue
            m = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?", addr.strip())
            if not m:
                continue
            street, city, st, z = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
            if st != state:
                continue

            price = None
            pm = re.search(r"\$([\d,]+)", price_text)
            if pm:
                try:
                    price = float(pm.group(1).replace(",", ""))
                except ValueError:
                    pass

            out.append(
                Listing(
                    source="national.auction_dot_com",
                    source_url=link,
                    listing_type=_ltype_from_status(status_text),
                    property_kind=_kind(kind_text),
                    street_address=street,
                    city=city,
                    state=st,
                    zip_code=z,
                    opening_bid=price,
                    description=f"Auction.com {status_text or 'foreclosure'}",
                    auction_status=status_text or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"auction_dot_com": {
                        "status": status_text,
                        "kind_text": kind_text,
                    }},
                )
            )
        except Exception:
            continue

    return out


class AuctionDotCom(BaseScraper):
    slug = "national.auction_dot_com"
    name = "Auction.com"
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
                log.info("auction_dot_com.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("auction_dot_com.state_failed", state=state, error=str(exc)[:200])
        return out
