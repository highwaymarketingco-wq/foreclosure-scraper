"""NC public legal notices via ncnotices.com (NC Press Association aggregator).

The site is ASP.NET WebForms with session-based URLs (the path includes a
session token like /(S(...))/default.aspx). Direct HTTP fails because of
__VIEWSTATE / session handshake. Scrapling stealth-renders + drives the
search form to extract foreclosure-relevant notices.

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

BASE = "https://www.ncnotices.com/"
QUERIES = (
    "foreclosure sale",
    "substitute trustee",
    "upset bid",
    "tax foreclosure",
)

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
COUNTY_RE = re.compile(
    r"\b(Mecklenburg|Buncombe|Henderson|Gaston|Cleveland|Rutherford|Polk|"
    r"Burke|McDowell|Lincoln|Madison|Yancey|Mitchell|Transylvania)\s+County\b",
    re.I,
)


def _classify(text: str) -> ListingType:
    t = text.lower()
    if "tax foreclosure" in t or "tax sale" in t:
        return ListingType.TAX_SALE
    if "sheriff" in t:
        return ListingType.SHERIFF_SALE
    return ListingType.FORECLOSURE_SALE


async def _search_one(query: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("ncnotices.scrapling_missing")
        return []

    async def page_action(page):
        try:
            # Wait for site to load (session token redirect should resolve)
            await page.wait_for_load_state("networkidle", timeout=15000)
            # Find search input — multiple possible selectors
            search_sel = ("input[name*='search'], input[name*='keyword'], "
                          "input[id*='search'], input[id*='keyword'], "
                          "input[type='search'], input[placeholder*='earch']")
            try:
                await page.fill(search_sel, query, timeout=10000)
            except Exception:
                # fallback: try first text input
                await page.locator("input[type='text']").first.fill(query)
            # Submit — try button click then keyboard
            for btn in ("button[type='submit']", "input[type='submit']", "button.search"):
                try:
                    await page.click(btn, timeout=3000)
                    break
                except Exception:
                    continue
            else:
                await page.keyboard.press("Enter")
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            BASE, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("ncnotices.fetch_fail", query=query, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html:
        return []

    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()

    # ncnotices result cards — try multiple structures
    cards = tree.css(
        "div.search-result, div.result, article.notice, "
        "tr.searchResultRow, div[class*='notice']"
    )
    if not cards:
        # Fallback: any element with notice-style content (paragraphs containing
        # 'foreclosure' + addresses)
        cards = [p for p in tree.css("p, li, div") if "foreclos" in p.text().lower()][:200]

    for card in cards:
        text = card.text(strip=True)
        if not text or len(text) < 50:
            continue
        # Skip nav/footer text
        if any(s in text.lower() for s in ("login", "subscribe", "navigation menu")):
            continue

        a = card.css_first("a[href]")
        href = (a.attributes.get("href", "") if a else "") or BASE
        if href.startswith("/"):
            href = f"https://www.ncnotices.com{href}"

        addr_m = ADDR_RE.search(text)
        county_m = COUNTY_RE.search(text)
        county = county_m.group(1).title() if county_m else None

        # Dedup by content snippet
        sig = (addr_m.group(1) if addr_m else text[:80]).strip().lower()
        if sig in seen:
            continue
        seen.add(sig)

        out.append(
            Listing(
                source="public_notices.ncnotices",
                source_url=href,
                listing_type=_classify(text),
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr_m.group(1) if addr_m else None,
                state="NC",
                county=county,
                description=text[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"ncnotices": {"query": query, "snippet": text[:800]}},
            )
        )

    return out


class PublicNoticeNC(BaseScraper):
    slug = "public_notices.ncnotices"
    name = "NC Notices (NC Press Association)"
    category = "public_notice"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_overall: set[str] = set()
        for q in QUERIES:
            try:
                listings = await _search_one(q)
                for li in listings:
                    sig = (li.street_address or li.description[:80]).lower()
                    if sig in seen_overall:
                        continue
                    seen_overall.add(sig)
                    out.append(li)
                log.info("ncnotices.query_done", query=q, count=len(listings))
            except Exception as exc:
                log.warning("ncnotices.query_failed", query=q, error=str(exc)[:200])
        return out
