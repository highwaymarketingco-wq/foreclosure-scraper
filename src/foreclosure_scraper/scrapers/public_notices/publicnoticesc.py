"""publicnoticesc.com — South Carolina Press Association legal notice aggregator.

Cloudflare-protected. Original implementation depended on Apify rag-web-browser.
This rewrite uses Scrapling's StealthyFetcher (camoufox/Playwright stealth)
which handles the Cloudflare JS challenge directly without paid Apify access.

Free, no Apify dependency.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import SC_COUNTIES
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.publicnoticesc.com"
SEARCH_URL = f"{BASE}/Search.aspx"
QUERIES = (
    "foreclosure",
    "master in equity",
    "tax sale",
)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)


def _classify(text: str) -> ListingType:
    t = text.lower()
    if "tax sale" in t or "tax foreclosure" in t:
        return ListingType.TAX_SALE
    if "master in equity" in t or "master-in-equity" in t:
        return ListingType.FORECLOSURE_SALE
    if "sheriff" in t:
        return ListingType.SHERIFF_SALE
    return ListingType.FORECLOSURE_SALE


async def _search_county(county_name: str, query: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("publicnoticesc.scrapling_missing")
        return []

    params = {"keyword": query, "category": "Foreclosures", "county": county_name}
    url = f"{SEARCH_URL}?{urlencode(params)}"

    try:
        result = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=120000,
        )
    except Exception as exc:
        log.warning("publicnoticesc.fetch_fail", county=county_name, query=query,
                    error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 2000:
        return []

    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()

    cards = tree.css(
        "div.search-result, div.notice-item, tr.searchResultRow, "
        "div[class*='notice'], article"
    )
    if not cards:
        cards = [p for p in tree.css("p, li, div") if "foreclos" in p.text().lower()][:200]

    for card in cards:
        text = card.text(strip=True)
        if not text or len(text) < 50:
            continue
        if any(s in text.lower() for s in ("login", "subscribe", "navigation")):
            continue
        a = card.css_first("a[href]")
        href = (a.attributes.get("href", "") if a else "") or url
        if href.startswith("/"):
            href = f"{BASE}{href}"
        addr_m = ADDR_RE.search(text)
        sig = (addr_m.group(1) if addr_m else text[:80]).strip().lower()
        if sig in seen:
            continue
        seen.add(sig)

        out.append(
            Listing(
                source="public_notices.publicnoticesc",
                source_url=href,
                listing_type=_classify(text),
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr_m.group(1) if addr_m else None,
                state="SC",
                county=county_name,
                description=text[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"publicnoticesc": {"query": query, "snippet": text[:800]}},
            )
        )

    return out


class PublicNoticeSC(BaseScraper):
    slug = "public_notices.publicnoticesc"
    name = "Public Notice SC (SCPA)"
    category = "public_notice"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        # Only top-volume counties to bound rendering cost — each fetch takes
        # several seconds via Scrapling stealth.
        priority = [c for c in SC_COUNTIES
                    if c.name in ("Spartanburg", "Anderson", "Pickens", "Cherokee", "Oconee")]
        out: list[Listing] = []
        for county in priority:
            for q in QUERIES:
                try:
                    listings = await _search_county(county.name, q)
                    out.extend(listings)
                    log.info("publicnoticesc.query_done", county=county.name,
                             query=q, count=len(listings))
                except Exception as exc:
                    log.warning("publicnoticesc.query_failed", county=county.name,
                                query=q, error=str(exc)[:200])
        return out
