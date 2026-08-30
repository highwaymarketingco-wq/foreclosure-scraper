"""Korn Law Firm — DEAD (domain parked).

The kornlawfirm.com domain no longer hosts the firm's website. Both
/foreclosure-sales/ and /sales/ serve a FingerprintJS parking shim that
redirects to a domain-ad service (ron.mamma.com on 2026-05-13,
yfdabv11.com on 2026-05-14). The scraper is intentionally retained as a
stub so the slug stays known but skipped; fetch() returns [] without
doing network work.

If the firm ever republishes (new domain or restored site), revert this
commit to get the working stealth/parser logic back.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ._helpers import ADDR_RE, COUNTY_RE, DATE_RE, parse_blocks

URLS = (
    "https://www.kornlawfirm.com/foreclosure-sales/",
    "https://www.kornlawfirm.com/sales/",
)

BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


async def _fetch_url(url: str) -> str:
    """Drive the click-through 'Enter' splash + wait for listings."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return ""

    async def page_action(page):
        # Splash entry click — Korn uses various button shapes
        for sel in (
            'a:has-text("Click here to enter")',
            'a:has-text("Enter")',
            'button:has-text("Enter")',
            'a:has-text("Accept")',
            'a.enter-button',
        ):
            try:
                await page.click(sel, timeout=4000)
                await page.wait_for_load_state("networkidle", timeout=12000)
                break
            except Exception:
                continue
        # Wait for any listings to appear
        for sel in (
            "table tbody tr",
            "div.foreclosure-list",
            "div.sale-listing",
            "article",
        ):
            try:
                await page.wait_for_selector(sel, timeout=15000)
                break
            except Exception:
                continue
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    try:
        # FORECLOSURE_NO_CF_SOLVE=1 disables Cloudflare/Turnstile SOLVING (compliant run);
        # the page then simply fails to render rather than defeating the challenge.
        import os as _os
        _solve = _os.environ.get("FORECLOSURE_NO_CF_SOLVE", "").strip().lower() not in ("1", "true", "yes")
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True,
            timeout=180000, page_action=page_action,
            solve_cloudflare=_solve,
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
            if li:
                _add_unique(li, out, seen)

    # Path B: card/article fallback
    if not out:
        for sel in ("article", "div.sale-listing", "div.foreclosure-list li"):
            for node in tree.css(sel):
                text = node.text(separator=" ", strip=True)
                if not text or len(text) < 30:
                    continue
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
                li.state = "SC"  # Korn is SC-only
                _add_unique(li, out, seen)
    return out


def _parse_chunk(text: str, url: str, slug: str) -> Listing | None:
    addr_m = ADDR_RE.search(text)
    if not addr_m:
        return None
    county_m = COUNTY_RE.search(text)
    date_m = DATE_RE.search(text)
    bid_m = BID_RE.search(text)

    sale_date = None
    if date_m:
        try:
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            pass

    bid = None
    if bid_m:
        try:
            v = float(bid_m.group(1).replace(",", ""))
            if 100 <= v <= 5_000_000:
                bid = v
        except ValueError:
            pass

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",  # Korn is SC-only
        county=county_m.group(1) if county_m else None,
        street_address=addr_m.group(1),
        sale_date=sale_date,
        opening_bid=bid,
        description=f"Korn Law Firm trustee sale: {text[:200]}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )


def _add_unique(li: Listing, out: list, seen: set[str]) -> None:
    key = (li.street_address or "").upper() + "|" + (li.county or "")
    if key.strip("|") in seen:
        return
    seen.add(key.strip("|"))
    out.append(li)


class Korn(BaseScraper):
    slug = "law_firms.korn"
    name = "Korn Law Firm (SC, stealth)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        # Domain dead since 2026-05-13 — skip network entirely.
        return []
