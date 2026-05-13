"""Aldridge Pite — NC foreclosure trustee.

Disclaimer-gated: aldridgepite.com requires clicking "I Agree" on the
NC disclaimer page before the listings table renders. Uses Scrapling
stealth and drives the disclaimer modal click.

Sites:
  NC: /sale-day-listings-selection/foreclosure-listings-north-carolina/
Disclaimer page: /disclaimer-north-carolina/ — clicking I-Agree sets
a session cookie that unlocks the listings page.

SC support removed 2026-05-13: every variant of the SC URL
(/sale-day-listings-selection/foreclosure-listings-south-carolina/,
/disclaimer-south-carolina/, /disclaimer-sc/, etc.) now 404s.
Aldridge appears to have exited the SC market.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

URLS = (
    ("https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/", "NC"),
)


async def _fetch_state(url: str) -> str:
    """Drive the disclaimer-modal accept flow via Scrapling stealth.
    Returns the listings HTML (table content) or empty string on failure."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return ""

    async def page_action(page):
        # If we landed on the disclaimer page, click the agree button.
        # Aldridge Pite uses different button shapes across templates;
        # try several.
        for sel in (
            'a:has-text("I AGREE")',
            'a:has-text("I Agree")',
            'button:has-text("I AGREE")',
            'button:has-text("Accept")',
            'a:has-text("Accept")',
            'a.disclaimer-accept',
            'input[type="submit"][value*="Agree" i]',
        ):
            try:
                await page.click(sel, timeout=4000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                break
            except Exception:
                continue
        # Wait for the listings table to render
        try:
            await page.wait_for_selector(
                "table.posts-data-table, table tbody tr",
                timeout=20000,
            )
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
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


def _parse_listings(html: str, url: str, state: str, slug: str) -> list[Listing]:
    if not html:
        return []
    tree = HTMLParser(html)
    table = tree.css_first("table.posts-data-table") or tree.css_first("table tbody")
    if not table:
        return []

    out: list[Listing] = []
    for tr in table.css("tbody tr"):
        cells = [td.text(strip=True) for td in tr.css("td")]
        if len(cells) < 6:
            continue
        # Column layout (verified 2026-04 NC): File# | Address | City | State | Zip | County | Sale Date | Bid
        # Different page versions vary; try positional then keyword-fallback.
        file_no = cells[0] if len(cells) > 0 else ""
        addr = cells[1] if len(cells) > 1 else ""
        city = cells[2] if len(cells) > 2 else ""
        state_cell = cells[3] if len(cells) > 3 else state
        zip_code = cells[4] if len(cells) > 4 else ""
        county = cells[5] if len(cells) > 5 else ""
        bid_raw = cells[-1]  # Bid is always last column
        if not addr or not file_no:
            continue

        bid = None
        bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw or "")
        if bm:
            try:
                bid = float(bm.group(1).replace(",", ""))
            except ValueError:
                pass

        out.append(
            Listing(
                source=slug,
                source_url=url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr or None,
                city=city or None,
                state=(state_cell or state).upper()[:2],
                zip_code=zip_code or None,
                county=(county or "").replace(" County", "") or None,
                case_number=file_no or None,
                opening_bid=bid,
                description=f"Aldridge Pite trustee sale — file {file_no}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
    return out


class AldridgePite(BaseScraper):
    slug = "law_firms.aldridge_pite"
    name = "Aldridge Pite (disclaimer-gated, stealth)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 240.0  # NC only (~180s + slack) since SC URL is dead

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url, state in URLS:
            html = await _fetch_state(url)
            out.extend(_parse_listings(html, url, state, self.slug))
        return out
