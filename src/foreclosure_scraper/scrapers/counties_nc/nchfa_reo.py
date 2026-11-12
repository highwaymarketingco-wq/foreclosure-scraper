"""NC Housing Finance Agency — REO properties for sale.

NCHFA publishes a list of REO (Real Estate Owned) properties available
for purchase at nchfa.com/home-buyers/properties-sale.  These are
properties that have been foreclosed on and are now owned by the state
agency, offered for sale to qualified buyers.

State agency REO list — updated twice monthly.  Good pre-sale distress
signal: the property has already completed foreclosure and is now
being liquidated.

Free, public, no login.
Slug: counties_nc.nchfa_reo
Category: reo
ListingType: REO
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.nchfa.com/home-buyers/properties-sale"


class NCHFAREO(BaseScraper):
    slug = "counties_nc.nchfa_reo"
    name = "NC Housing Finance Agency REO Properties"
    category = "reo"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("nchfa_reo.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # NCHFA lists properties in tables or property cards
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)

        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("address", "city", "county", "price", "bed", "bath", "#")):
                continue

            addr = clean[0] if clean else None
            city = clean[1] if len(clean) > 1 else None
            price = None
            for c in clean:
                m = re.search(r"\$[\d,]+", c)
                if m:
                    try:
                        price = float(m.group().replace("$", "").replace(",", ""))
                    except ValueError:
                        pass

            # Extract county if present
            county = None
            for c in clean:
                if "county" in c.lower():
                    county = re.sub(r"(?i)\s*county\s*", "", c).strip()
                    break

            # Extract beds/baths
            beds = None
            baths = None
            for c in clean:
                m = re.search(r"(\d+)\s*bed", c, re.I)
                if m:
                    beds = float(m.group(1))
                m = re.search(r"(\d+(?:\.\d+)?)\s*bath", c, re.I)
                if m:
                    baths = float(m.group(1))

            out.append(Listing(
                source="counties_nc.nchfa_reo",
                source_url=PAGE_URL,
                listing_type=ListingType.REO,
                property_kind=PropertyKind.SINGLE_FAMILY,
                state="NC",
                county=county,
                street_address=addr,
                city=city,
                opening_bid=price,
                bedrooms=beds,
                bathrooms=baths,
                description=" | ".join(clean[:8]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"nchfa_reo": {"cells": clean[:12]}},
            ))

        # Fallback: look for property cards/divs
        if not out:
            cards = re.findall(r'<div[^>]*class="[^"]*(?:property|listing|card|home)[^"]*"[^>]*>(.*?)</div>', html, re.I | re.S)
            for card in cards:
                text = re.sub(r"<[^>]+>", " ", card)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) < 10:
                    continue
                addr_match = re.search(r"\d+\s+\w+[\w\s]+(?:st|ave|rd|dr|ln|ct|blvd|hwy|way|pl|cir|trl|pkwy|ter)", text, re.I)
                addr = addr_match.group().strip() if addr_match else None
                city_match = re.search(r",\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*NC", text)
                city = city_match.group(1) if city_match else None
                price_match = re.search(r"\$[\d,]+", text)
                price = None
                if price_match:
                    try:
                        price = float(price_match.group().replace("$", "").replace(",", ""))
                    except ValueError:
                        pass
                if not addr and not price:
                    continue
                out.append(Listing(
                    source="counties_nc.nchfa_reo",
                    source_url=PAGE_URL,
                    listing_type=ListingType.REO,
                    property_kind=PropertyKind.SINGLE_FAMILY,
                    state="NC",
                    street_address=addr,
                    city=city,
                    opening_bid=price,
                    description=text[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"nchfa_reo": {"text": text[:200]}},
                ))

        log.info("nchfa_reo.done", count=len(out))
        return out
