"""US Marshals Service real-property forfeiture sales.

The US Marshals Service auctions forfeited real property from criminal cases.
These are genuine motivated-seller leads: the government is liquidating seized
properties, often at steep discounts.

Source: https://www.usmarshals.gov/what-we-do/asset-forfeiture/real-property
The page links to current auctions hosted on GSAAuctions.gov and other platforms.

Volume is small (typically 20-50 properties nationwide) but includes residential,
commercial, and land. NC/SC hits are sporadic but high-value.

Free, no auth, plain HTML. The sales page itself is a simple HTML listing with
links to auction details.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://www.usmarshals.gov/what-we-do/asset-forfeiture/real-property/"
_CORE_STATES = {"NC", "SC"}

# State name -> code (USMS spells out state names in full).
_STATE_MAP = {
    "north carolina": "NC", "south carolina": "SC",
    "georgia": "GA", "tennessee": "TN", "virginia": "VA",
    "florida": "FL", "alabama": "AL",
}

# Address pattern: "123 Main St, City, ST 12345" or "City, State ZIP"
_ADDR_RE = re.compile(
    r"(\d{1,5}\s+[A-Z][\w .'\-]+(?:\s+[A-Z][\w .'\-]+)*)\s*,?\s*"
    r"([A-Z][\w .'\-]+?)\s*,\s*"
    r"([A-Za-z ]+)\s+(\d{5})",
    re.MULTILINE,
)

# Price pattern
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")

# Link to auction detail
_LINK_RE = re.compile(r'href=["\']([^"\']*(?:gsaauctions|auction|bid)[^"\']*)["\']', re.I)


class USMarshalsRealProperty(BaseScraper):
    slug = "national.usmarshals_realproperty"
    name = "US Marshals Service Real Property Forfeiture Sales"
    category = "federal_reo"
    expected_min_count = 0  # Sporadic; often 0 in NC/SC
    requires_apify = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        try:
            html = await get_text(_URL, impersonate=True, timeout=60.0)
        except Exception as exc:
            log.warning("usmarshals.fetch_failed", error=str(exc)[:200])
            return []

        if not html or len(html) < 500:
            log.warning("usmarshals.empty_response", size=len(html))
            return []

        tree = HTMLParser(html)
        body_text = tree.body.text(separator="\n") if tree.body else html

        out: list[Listing] = []
        seen: set[str] = set()

        # Find property blocks by scanning for address patterns.
        for m in _ADDR_RE.finditer(body_text):
            street, city, state_raw, zip_code = m.groups()
            state_raw = state_raw.strip()
            state = _STATE_MAP.get(state_raw.lower())
            if not state and len(state_raw) == 2:
                state = state_raw.upper()
            if state not in _CORE_STATES:
                continue

            key = f"{street.strip()}_{zip_code}"
            if key in seen:
                continue
            seen.add(key)

            # Look for price in the surrounding context.
            start = max(0, m.start() - 200)
            end = min(len(body_text), m.end() + 500)
            block = body_text[start:end]
            price = None
            pm = _PRICE_RE.search(block)
            if pm:
                try:
                    price = float(pm.group(1).replace(",", ""))
                except ValueError:
                    pass

            # Try to find an auction link in the surrounding HTML.
            html_block = html[start:end] if start < len(html) else ""
            link = None
            lm = _LINK_RE.search(html_block)
            if lm:
                link = lm.group(1)
                if link.startswith("/"):
                    link = f"https://www.usmarshals.gov{link}"

            out.append(Listing(
                source=self.slug,
                source_url=link or _URL,
                listing_type=ListingType.REO,
                property_kind=PropertyKind.UNKNOWN,
                street_address=street.strip(),
                city=city.strip(),
                state=state,
                zip_code=zip_code,
                opening_bid=price,
                description=f"US Marshals forfeited real property ({city.strip()}, {state})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "usmarshals": {
                        "forward_excerpt": block[:500],
                        "auction_url": link,
                    },
                },
            ))

        log.info("usmarshals.done", count=len(out))
        return out
