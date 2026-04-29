"""Mecklenburg County NC tax foreclosures via Kania Law Firm AJAX endpoint.

Page renders a Ninja Tables widget that calls admin-ajax.php with a nonce
scraped from the page HTML. We replicate the AJAX flow directly.
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

PAGE_URL = "https://kanialawfirm.com/tax-foreclosures-mecklenburg-county/foreclosure-listings/"
AJAX_URL = "https://kanialawfirm.com/wp-admin/admin-ajax.php"

NONCE_RE = re.compile(r'"nonce":"([a-f0-9]+)"')
TABLE_ID_RE = re.compile(r'"tableId":(\d+)')

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
PARCEL_RE = re.compile(r"\b(\d{5,10})\b")


class MecklenburgTaxForeclosures(BaseScraper):
    slug = "counties_nc.mecklenburg_tax"
    name = "Kania Law NC Tax Foreclosures (Mecklenburg)"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0  # often empty between auction cycles

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=30.0) as c:
            try:
                r = await c.get(PAGE_URL)
                if r.status_code != 200:
                    return []
                page_html = r.text
            except Exception:
                return []

            nonce_m = NONCE_RE.search(page_html)
            table_m = TABLE_ID_RE.search(page_html)
            if not nonce_m or not table_m:
                return []
            nonce = nonce_m.group(1)
            table_id = table_m.group(1)

            try:
                r = await c.get(
                    AJAX_URL,
                    params={
                        "action": "wp_ajax_ninja_tables_public_action",
                        "table_id": table_id,
                        "target_action": "get-all-data",
                        "default_sorting": "old_first",
                        "skip_rows": "0",
                        "limit_rows": "0",
                        "ninja_table_public_nonce": nonce,
                    },
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": PAGE_URL,
                    },
                )
                if r.status_code != 200:
                    return []
                data = r.json()
            except Exception:
                return []

        if not isinstance(data, list):
            return []

        out: list[Listing] = []
        for row in data:
            county = (row.get("county") or "").replace(" County", "").strip()
            if county.lower() != "mecklenburg":
                continue
            sale_raw = row.get("saledate") or ""
            sale_date = None
            if sale_raw:
                try:
                    sale_date = dateparser.parse(sale_raw)
                except (ValueError, TypeError):
                    pass

            addr_html = row.get("addressparcel") or ""
            addr_text = unescape(re.sub(r"<[^>]+>", " ", addr_html))
            addr_m = ADDR_RE.search(addr_text)
            parcel_m = PARCEL_RE.search(addr_text)

            bid = None
            for k in ("openingbid", "currentbid"):
                v = row.get(k)
                if v:
                    bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", str(v))
                    if bm:
                        try:
                            bid = float(bm.group(1).replace(",", ""))
                            break
                        except ValueError:
                            pass

            out.append(
                Listing(
                    source=self.slug,
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr_m.group(1) if addr_m else None,
                    state="NC",
                    county="Mecklenburg",
                    parcel_id=parcel_m.group(1) if parcel_m else None,
                    sale_date=sale_date,
                    opening_bid=bid,
                    case_number=row.get("courtfile"),
                    description=addr_text[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
        return out
