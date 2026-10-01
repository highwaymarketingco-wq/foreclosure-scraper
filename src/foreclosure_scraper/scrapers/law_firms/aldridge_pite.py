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

    # Map columns by header name rather than a fixed position. Live-verified
    # 2026-10-01: the real header is File Number | Address | City | State |
    # Zip | County | Date Listed | Current Bid | hf:tax:county — a 9th,
    # `data-visible="false"` taxonomy-filter column WordPress Posts Table Pro
    # still server-renders a <td> for. The old code read `cells[-1]` for the
    # bid, which that hidden trailing column would silently turn into the
    # bid (reading a taxonomy term as a dollar amount) the next time this
    # table actually has rows — a latent "silent success" bug, not yet
    # tripped only because the table is empty right now. It also never read
    # "Date Listed" at all, so sale_date was always None.
    header_row = table.css_first("thead tr")
    header = [th.text(strip=True).lower() for th in header_row.css("th,td")] if header_row else []
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        if "file" in h: idx.setdefault("file", i)
        elif "address" in h: idx.setdefault("addr", i)
        elif "city" in h: idx.setdefault("city", i)
        elif h == "state": idx.setdefault("state", i)
        elif "zip" in h: idx.setdefault("zip", i)
        elif "county" in h and not h.startswith("hf"): idx.setdefault("county", i)
        elif "date" in h: idx.setdefault("date", i)
        elif "bid" in h: idx.setdefault("bid", i)
    # Fallback to the documented positional layout if no thead was found
    # (defensive only — every live fetch so far has had one).
    if not idx:
        idx = {"file": 0, "addr": 1, "city": 2, "state": 3, "zip": 4, "county": 5, "date": 6, "bid": 7}

    out: list[Listing] = []
    for tr in table.css("tbody tr"):
        cells = [td.text(strip=True) for td in tr.css("td")]
        if len(cells) <= max(idx.values(), default=0):
            continue

        def cell(key: str) -> str:
            i = idx.get(key)
            return cells[i] if i is not None and i < len(cells) else ""

        file_no = cell("file")
        addr = cell("addr")
        city = cell("city")
        state_cell = cell("state") or state
        zip_code = cell("zip")
        county = cell("county")
        bid_raw = cell("bid")
        date_raw = cell("date")
        if not addr or not file_no:
            continue

        bid = None
        bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw or "")
        if bm:
            try:
                bid = float(bm.group(1).replace(",", ""))
            except ValueError:
                pass

        sale_date = None
        if date_raw:
            try:
                sale_date = datetime.fromisoformat(date_raw)
            except ValueError:
                try:
                    from dateutil import parser as dateparser
                    sale_date = dateparser.parse(date_raw)
                except (ValueError, TypeError, OverflowError):
                    sale_date = None

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
                sale_date=sale_date,
                opening_bid=bid,
                description=f"Aldridge Pite trustee sale — file {file_no}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"aldridge_pite": {"date_listed_raw": date_raw or None}},
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
