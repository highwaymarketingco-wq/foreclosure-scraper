"""Aldridge Pite — NC foreclosure trustee.

Compliant plain fetch (no bot-detection bypass). aldridgepite.com 301s the
listings page to its NC disclaimer page UNLESS the request carries a Referer
of that disclaimer page; with that header it returns HTTP 200 with the
listings table rendered server-side (WordPress Posts Table Pro, serverSide
:false — the rows are in the static HTML, no admin-ajax round-trip). So a
normal GET + Referer is all that's needed — no stealth browser, no
solve_cloudflare, no challenge handling.

Sites:
  NC: /sale-day-listings-selection/foreclosure-listings-north-carolina/
Referer used: /disclaimer-north-carolina/

SC support removed 2026-05-13: every variant of the SC URL now 404s
(Aldridge appears to have exited the SC market).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URLS = (
    ("https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/", "NC"),
)

# Sending the disclaimer page as Referer is what unlocks the listings page
# (otherwise it 301s back to the disclaimer). This is a normal HTTP header,
# not a bot-detection bypass.
_REFERER = "https://aldridgepite.com/disclaimer-north-carolina/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _REFERER,
}


async def _fetch_state(url: str) -> str:
    """Plain GET with a disclaimer Referer. Returns the listings HTML (table
    content) or empty string on failure. No bot-detection bypass."""
    try:
        async with client(timeout=30.0) as c:
            r = await c.get(url, headers=_HEADERS)
            if r.status_code != 200:
                return ""
            return r.text
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
    name = "Aldridge Pite (NC, plain fetch + disclaimer Referer)"
    category = "law_firm"
    requires_apify = False
    requires_render = False
    expected_min_count = 0  # NC table is often empty between sale cycles
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url, state in URLS:
            html = await _fetch_state(url)
            out.extend(_parse_listings(html, url, state, self.slug))
        return out
