"""Treasury seized real-property auctions — federal REO source.

US Treasury seizes real property in tax/criminal forfeiture cases and
publishes upcoming auctions at:

  https://www.treasury.gov/auctions/treasury/rp/realprop.shtml

Volume is small (~20 properties nationwide at any time) but they're
zero-competition — the public doesn't know to look here.

Free, no auth, plain HTML. Refresh cadence is irregular (case-driven).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


URL = "https://www.treasury.gov/auctions/treasury/rp/realprop.shtml"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# Address with state suffix — Treasury format is consistent: city, state zip
ADDR_RE = re.compile(
    r"\b(\d{1,5}\s+[A-Z][\w .'\-]+?)\s*,?\s*"
    r"([A-Z][\w .'\-]+?),\s*([A-Z]{2})\s*(\d{5})\b",
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"
)
PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


class TreasurySeizedRealProperty(BaseScraper):
    slug = "reo.treasury_seized"
    name = "US Treasury Seized Real Property"
    category = "federal_reo"
    expected_min_count = 0   # Sometimes 0; max ~20 nationwide
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=30.0) as c:
            try:
                r = await c.get(URL, headers=HEADERS)
            except Exception as exc:
                log.warning("treasury_seized.fetch_failed", error=str(exc)[:200])
                return []
        # Lower bound chosen to accept valid small responses while still
        # filtering out error pages / empty responses. Real Treasury page
        # is ~120KB; a 1KB body is essentially "no listings."
        if r.status_code != 200 or len(r.text) < 1000:
            return []

        tree = HTMLParser(r.text)
        # The properties live in a series of div.property or table rows.
        # Without a per-element selector we anchor on the address regex,
        # taking the surrounding 1KB of context as the property block.
        body = tree.body.text(separator="\n") if tree.body else r.text
        out: list[Listing] = []
        seen: set[str] = set()

        for m in ADDR_RE.finditer(body):
            street, city, state, zip_code = m.groups()
            # Only NC + SC for our footprint; Treasury data is national.
            if state not in ("NC", "SC"):
                continue
            key = (street.strip(), city.strip(), state, zip_code)
            if key in seen:
                continue
            seen.add(key)

            # Block of text AFTER the match (for date + price extraction).
            # Looking only forward avoids picking up the prior listing's
            # price/date when listings are stacked in the same page.
            block = body[m.end():m.end() + 400]
            sale_date = None
            dm = DATE_RE.search(block)
            if dm:
                from dateutil import parser as dp
                try:
                    sale_date = dp.parse(dm.group(1), fuzzy=True)
                except (ValueError, TypeError):
                    sale_date = None
            price = None
            pm = PRICE_RE.search(block)
            if pm:
                try:
                    price = float(pm.group(1).replace(",", ""))
                except ValueError:
                    price = None

            out.append(Listing(
                source=self.slug,
                source_url=URL,
                listing_type=ListingType.REO,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                street_address=street.strip(),
                city=city.strip(),
                zip_code=zip_code,
                opening_bid=price,
                sale_date=sale_date,
                description=f"US Treasury seized real-property auction ({state})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"treasury_seized": {"forward_excerpt": block[:500]}},
            ))
        log.info("treasury_seized.done", count=len(out))
        return out
