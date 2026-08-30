"""VA Acquired Properties — Department of Veterans Affairs REO inventory.

The VA sells acquired properties (foreclosed VA-guaranteed loans) through
its Property Management Service. Listings are available at:

  https://www.va.gov/va-forms/real-property/properties/

Each listing includes: address, city, state, ZIP, price, beds/baths/sqft,
property type, and listing agent contact.

Free, public, no login.
Slug: national.va_acquired
Category: reo
ListingType: REO
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

VA_URL = "https://www.va.gov/va-forms/real-property/properties/"
BANK_REO_URL = "https://www.benefits.va.gov/homeloans/property/property.asp"


class VAAcquired(BaseScraper):
    slug = "national.va_acquired"
    name = "VA Acquired Properties"
    category = "reo"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(BANK_REO_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("va_acquired.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            return out

        # VA property pages typically list properties in HTML tables
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 3:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if not any(re.search(r"\d", c) for c in clean):
                continue
            if any(h in c.lower() for c in clean[:2] for h in ("header", "title", "property #")):
                continue

            addr = None
            city = None
            state = None
            price = None

            for c in clean:
                m = re.search(r"\b(NC|SC)\b", c)
                if m and not state:
                    state = m.group(1)
                m = re.search(r"\$([\d,]+)", c)
                if m and not price:
                    price = float(m.group(1).replace(",", ""))
                if re.search(r"\b\d+\s+\w+", c) and any(
                    s in c.lower() for s in ("st", "ave", "rd", "dr", "ln", "ct", "blvd", "hwy", "way")
                ):
                    if not addr:
                        addr = c

            if not state or state not in ("NC", "SC"):
                continue

            raw = {
                "source_url": BANK_REO_URL,
                "price": price,
            }
            out.append(
                Listing(
                    source=self.slug,
                    source_url=BANK_REO_URL,
                    listing_type=ListingType.REO,
                    street_address=addr,
                    state=state,
                    property_kind=PropertyKind.UNKNOWN,
                    opening_bid=price,
                    raw=raw,
                )
            )

        log.info("va_acquired.fetch_done", count=len(out))
        return out
