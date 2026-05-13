"""McMichael Taylor Gray — DISABLED (data moved to PowerBI iframe 2026-05).

mtglaw.com/foreclosure-sales/ no longer renders an HTML table. Instead
the listings are inside an embedded PowerBI dashboard:
  https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1IiwidCI6IjEzZDFlNzhjLTgyNDgtNGVlYS04OWY3LWQzNGIzZWJkOGM3OSIsImMiOjN9

Properly scraping this requires PowerBI-specific work (drive Playwright
into the iframe, wait 15-30s for the dashboard to render, expand state/
county filters, parse virtualized row divs with [role="row"]) — a
multi-hour rewrite plus tests, and inherently more fragile than HTML.

fetch() returns [] until that rewrite lands. Slug stays in KNOWN_FIXED
so run_health labels it correctly; "EMPTY (verified)" rather than "RENDER-
REQUIRED" because the issue is upstream design, not our stealth.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ._helpers import (
    ADDR_RE,
    COUNTY_RE,
    DATE_RE,
    PARCEL_RE,
    parse_blocks,
)

URLS = (
    "https://www.mtglaw.com/foreclosure-sales/",
    "https://www.mtglaw.com/sales/",
)

# Opening bid pattern for MTG listings
BID_RE = re.compile(
    r"(?:opening|minimum|starting)?\s*bid[:\s]*\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
BARE_BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# State indicator — MTG works NC + GA only, ignore other states
STATE_RE = re.compile(r"\b(NC|GA|SC)\b")


async def _fetch_url(url: str) -> str:
    """Scrapling stealth fetch with AJAX-completion wait."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return ""

    async def page_action(page):
        # Wait for any indicator that the AJAX listing-load completed.
        # MTG uses various table/list templates across redesigns; try a
        # broad set then settle on networkidle.
        for sel in (
            "table tbody tr",
            "div.listings",
            "div.foreclosure-listing",
            ".sales-listing",
        ):
            try:
                await page.wait_for_selector(sel, timeout=15000)
                break
            except Exception:
                continue
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True,
            timeout=180000, page_action=page_action,
            solve_cloudflare=True,
        )
        body = getattr(result, "body", b"")
        return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    except Exception:
        return ""


def _parse_html(html: str, url: str, slug: str) -> list[Listing]:
    if not html or len(html) < 1000:
        return []
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()

    # Path A: structured table rows
    for table in tree.css("table"):
        for row in table.css("tr"):
            text = row.text(separator=" ", strip=True)
            if not text or len(text) < 30:
                continue
            li = _parse_chunk(text, url, slug)
            if li and _add_unique(li, out, seen):
                continue

    # Path B: list/card divs
    if not out:
        for sel in ("div.listings li", "div.foreclosure-listing", ".sales-listing", "li.sale"):
            for node in tree.css(sel):
                text = node.text(separator=" ", strip=True)
                li = _parse_chunk(text, url, slug)
                if li:
                    _add_unique(li, out, seen)

    # Path C: text-block fallback
    if not out:
        body = tree.body
        if body:
            text = body.text(separator="\n")
            for li in parse_blocks(text, source_slug=slug, source_url=url):
                li.listing_type = ListingType.FORECLOSURE_SALE
                _add_unique(li, out, seen)
    return out


def _parse_chunk(text: str, url: str, slug: str) -> Listing | None:
    addr_m = ADDR_RE.search(text)
    if not addr_m:
        return None
    county_m = COUNTY_RE.search(text)
    date_m = DATE_RE.search(text)
    parcel_m = PARCEL_RE.search(text)
    state_m = STATE_RE.search(text)
    bid_m = BID_RE.search(text) or BARE_BID_RE.search(text)

    # MTG works NC + GA only — skip listings clearly from other states
    state = state_m.group(1) if state_m else "NC"
    if state not in ("NC", "SC", "GA"):
        return None

    sale_date = None
    if date_m:
        try:
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            pass

    bid = None
    if bid_m:
        try:
            bid = float(bid_m.group(1).replace(",", ""))
            if not (100 <= bid <= 5_000_000):
                bid = None
        except ValueError:
            pass

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county_m.group(1) if county_m else None,
        street_address=addr_m.group(1),
        sale_date=sale_date,
        parcel_id=parcel_m.group(1) if parcel_m else None,
        opening_bid=bid,
        description=f"McMichael Taylor Gray trustee sale: {text[:200]}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )


def _add_unique(li: Listing, out: list, seen: set[str]) -> bool:
    key = (li.street_address or "").upper() + "|" + (li.county or "")
    if key.strip("|") in seen:
        return False
    seen.add(key.strip("|"))
    out.append(li)
    return True


class McMichaelTaylorGray(BaseScraper):
    slug = "law_firms.mcmichael_taylor_gray"
    name = "McMichael Taylor Gray (AJAX-rendered, stealth)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        # Listings moved into a PowerBI iframe in May 2026. HTML-based
        # parsing yields nothing. Skip the network call until a proper
        # PowerBI scraper is built (see module docstring).
        return []
        return out
