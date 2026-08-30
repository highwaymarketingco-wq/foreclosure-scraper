"""NC Bankruptcy Court — Public Sales Notices.

The NC Eastern and Middle Bankruptcy Court districts publish public
sale notices at:
  - nceb.uscourts.gov/Public-Sales-Notice (Eastern District)
  - ncmb.uscourts.gov/public-sales (Middle District)

These are bankruptcy trustee sales — properties being liquidated through
Chapter 7/13 bankruptcy proceedings.  The debtor is being forced to sell
real property to satisfy creditors.

We already cover bankruptcy filings via CourtListener, but this captures
the actual SALE notices — properties that have moved from filing to
liquidation, which is a later-stage distress signal.

Free, public, no login.
Slug: counties_nc.nc_bankruptcy_sales
Category: bankruptcy
ListingType: BANKRUPTCY
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

URLS = [
    ("Eastern", "https://www.nceb.uscourts.gov/Public-Sales-Notice"),
    ("Middle", "https://www.ncmb.uscourts.gov/public-sales"),
]


class NCBankruptcySales(BaseScraper):
    slug = "counties_nc.nc_bankruptcy_sales"
    name = "NC Bankruptcy Court Public Sales Notices"
    category = "bankruptcy"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for district, url in URLS:
            try:
                html = await get_text(url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("nc_bankruptcy_sales.fetch_fail", district=district, error=str(exc)[:160])
                continue

            if not html or len(html) < 200:
                continue

            # Bankruptcy court pages list sales in tables or list items
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)

            for row in rows:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
                if len(cells) < 2:
                    continue
                clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                if any(h in c.lower() for c in clean[:2] for h in ("case", "debtor", "trustee", "address", "#", "date")):
                    continue

                # Extract case number
                case_match = re.search(r"\b(\d{2,}-\d{4,}-\d{2,})\b", " ".join(clean))
                case_num = case_match.group(1) if case_match else None

                # Extract address
                addr = None
                for c in clean:
                    if re.search(r"\d+\s+\w+", c) and any(kw in c.lower() for kw in ("st", "ave", "rd", "dr", "ln", "ct", "blvd", "hwy", "way", "pl")):
                        addr = c
                        break
                if not addr:
                    for c in clean:
                        if re.search(r"\d+\s+\w+", c):
                            addr = c
                            break

                # Extract debtor name (usually first cell)
                debtor = clean[0] if clean else None

                # Extract sale date
                date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", " ".join(clean))
                sale_date = None
                if date_match:
                    try:
                        sale_date = datetime.strptime(date_match.group(1), "%m/%d/%Y")
                    except ValueError:
                        try:
                            sale_date = datetime.strptime(date_match.group(1), "%m/%d/%y")
                        except ValueError:
                            pass

                # Extract bid amount
                amount = None
                for c in clean:
                    m = re.search(r"\$[\d,]+", c)
                    if m:
                        try:
                            amount = float(m.group().replace("$", "").replace(",", ""))
                        except ValueError:
                            pass

                out.append(Listing(
                    source="counties_nc.nc_bankruptcy_sales",
                    source_url=url,
                    listing_type=ListingType.BANKRUPTCY,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county=f"{district} District",
                    case_number=case_num,
                    defendant=debtor,
                    street_address=addr,
                    sale_date=sale_date,
                    opening_bid=amount,
                    description=" | ".join(clean[:8]) if clean else None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"nc_bankruptcy_sales": {"district": district, "cells": clean[:10]}},
                ))

            # Fallback: look for list items
            if not out:
                items = re.findall(r"<li[^>]*>(.*?)</li>", html, re.I | re.S)
                for item in items:
                    text = re.sub(r"<[^>]+>", "", item).strip()
                    if len(text) < 20:
                        continue
                    if not any(kw in text.lower() for kw in ("sale", "auction", "property", "debtor", "case", "trustee")):
                        continue
                    case_match = re.search(r"\b(\d{2,}-\d{4,}-\d{2,})\b", text)
                    addr_match = re.search(r"\d+\s+\w+[\w\s]+(?:st|ave|rd|dr|ln|ct|blvd|hwy|way)", text, re.I)
                    out.append(Listing(
                        source="counties_nc.nc_bankruptcy_sales",
                        source_url=url,
                        listing_type=ListingType.BANKRUPTCY,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county=f"{district} District",
                        case_number=case_match.group(1) if case_match else None,
                        street_address=addr_match.group().strip() if addr_match else None,
                        description=text[:300],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"nc_bankruptcy_sales": {"district": district, "text": text[:200]}},
                    ))

        log.info("nc_bankruptcy_sales.done", count=len(out))
        return out
