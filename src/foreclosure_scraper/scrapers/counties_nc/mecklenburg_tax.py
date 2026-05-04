"""Mecklenburg County NC tax foreclosures via RBC Wealth Management page.

The Kania Law Firm page was deprecated. RBC Wealth Management now publishes
the Mecklenburg tax foreclosure list (legal counsel relationship) at
https://www.rbcwb.com/tax-foreclosure-listings/.

Page renders the data as plain HTML <tr> rows — no AJAX/JS needed.
Columns: Defendant | Address | ZIP | Parcel | Case# | Sale Date | (link)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

URL = "https://www.rbcwb.com/tax-foreclosure-listings/"


def _parse_sale_date(text: str) -> datetime | None:
    if not text or "no sale" in text.lower():
        return None
    try:
        return dateparser.parse(text, fuzzy=True)
    except (ValueError, TypeError):
        return None


class MecklenburgTax(BaseScraper):
    slug = "counties_nc.mecklenburg_tax"
    name = "Mecklenburg County (NC) — Tax Foreclosures (RBC)"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 5

    async def fetch(self) -> Iterable[Listing]:
        try:
            html = await get_text(URL, timeout=30.0)
        except Exception:
            return []
        tree = HTMLParser(html)
        rows = tree.css("tr")
        out: list[Listing] = []
        for row in rows:
            cells = [c.text(strip=True) for c in row.css("td")]
            if len(cells) < 5:
                continue
            defendant, addr, zip_code, parcel, case_no = cells[:5]
            sale_text = cells[5] if len(cells) > 5 else ""

            # Skip header rows
            if defendant.lower() in ("defendant", "name", ""):
                continue
            # Need at least an address or parcel
            if not addr or len(addr) < 4:
                continue

            # Address format: street + optional unit. Pull street.
            street = re.sub(r"\s+", " ", addr).strip()
            if street.lower().startswith("vacant lot"):
                kind = PropertyKind.LAND
            else:
                kind = PropertyKind.UNKNOWN

            sale_date = _parse_sale_date(sale_text)

            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=kind,
                    state="NC",
                    county="Mecklenburg",
                    street_address=street,
                    zip_code=zip_code.strip()[:5] if zip_code and zip_code.strip().isdigit() else None,
                    parcel_id=parcel.strip() if parcel and len(parcel.strip()) >= 5 else None,
                    case_number=case_no.strip() if case_no else None,
                    defendant=defendant.strip()[:200],
                    sale_date=sale_date,
                    description=f"Mecklenburg tax foreclosure — Case {case_no} ({sale_text or 'no sale date set'})",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"mecklenburg_tax": {
                        "sale_text": sale_text,
                        "publisher": "RBC Wealth Management (NC tax counsel)",
                    }},
                )
            )
        return out
