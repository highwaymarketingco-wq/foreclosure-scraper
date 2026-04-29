"""Buncombe County NC tax foreclosures via the public Trumba JSON calendar.

The taxforeclosures.buncombenc.gov page renders a Trumba calendar widget; we
bypass it and hit the JSON endpoint directly. Free, pure HTTP, no Apify needed.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

JSON_URL = "https://www.trumba.com/calendars/tax-foreclosures-all.json"


class BuncombeTax(BaseScraper):
    slug = "counties_nc.buncombe_tax"
    name = "Buncombe County (NC) Tax Foreclosures"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 1

    async def fetch(self) -> Iterable[Listing]:
        today = datetime.utcnow()
        params = {
            "startdate": today.strftime("%Y%m%d"),
            "enddate": (today + timedelta(days=400)).strftime("%Y%m%d"),
        }
        try:
            async with client(timeout=30.0) as c:
                r = await c.get(JSON_URL, params=params)
                if r.status_code != 200:
                    return []
                # Trumba returns a JSONP-like response sometimes; sniff the JSON body
                text = r.text
                start = text.find("{")
                if start < 0:
                    return []
                import json
                try:
                    data = json.loads(text[start:])
                except json.JSONDecodeError:
                    # Try parsing as raw JSON array
                    data = json.loads(text)
        except Exception:
            return []

        events = data if isinstance(data, list) else data.get("events", [])
        out: list[Listing] = []
        for ev in events:
            sd = ev.get("startDateTime") or ev.get("start") or ev.get("startdate")
            if not sd:
                continue
            try:
                sale_date = dateparser.parse(sd)
            except (ValueError, TypeError):
                continue

            title = ev.get("title", "")  # defendant name
            location = ev.get("location") or ""
            # location often contains an HTML <a> with the address; strip tags
            addr_m = re.search(
                r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
                r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
                re.sub(r"<[^>]+>", " ", location),
                re.I,
            )
            address = addr_m.group(1) if addr_m else None

            # Extract custom fields (case#, opening bid)
            case_num = None
            bid = None
            for cf in ev.get("customFields", []) or []:
                name = (cf.get("name") or "").lower()
                value = cf.get("value") or ""
                if "case" in name and value:
                    case_num = re.sub(r"<[^>]+>", " ", value).strip()
                elif ("opening" in name or "current" in name) and "bid" in name:
                    bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", value)
                    if bm:
                        try:
                            bid = float(bm.group(1).replace(",", ""))
                        except ValueError:
                            pass

            out.append(
                Listing(
                    source=self.slug,
                    source_url="https://taxforeclosures.buncombenc.gov/",
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=address,
                    state="NC",
                    county="Buncombe",
                    sale_date=sale_date,
                    case_number=case_num,
                    opening_bid=bid,
                    defendant=title.strip() or None,
                    description=re.sub(r"<[^>]+>", " ", ev.get("description") or "")[:400] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
        return out
