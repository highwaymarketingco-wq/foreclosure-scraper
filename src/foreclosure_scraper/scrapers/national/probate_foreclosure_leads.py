"""Probate / Foreclosure / Sheriff Sale / Tax Lien / Tax Sale national aggregator
via jungle_synthesizer/probate-foreclosure-leads-scraper (Apify).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...config import ALL_COUNTIES
from ...models import Listing, ListingType, PropertyKind

ACTOR = "jungle_synthesizer/probate-foreclosure-leads-scraper"

EVENT_TYPE_MAP = {
    "tax_lien": ListingType.TAX_LIEN,
    "tax_sale": ListingType.TAX_SALE,
    "sheriff_sale": ListingType.SHERIFF_SALE,
    "foreclosure": ListingType.FORECLOSURE_SALE,
    "probate": ListingType.LIS_PENDENS,
}


class ProbateForeclosureLeads(BaseScraper):
    slug = "national.probate_foreclosure_leads"
    requires_apify = True
    expected_min_count = 20
    name = "Probate/Foreclosure/Tax-Sale Leads (national open data)"
    category = "national_aggregator"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        county_names = [c.name for c in ALL_COUNTIES]
        run_input = {
            "eventTypes": ["foreclosure", "sheriff_sale", "tax_lien", "tax_sale"],
            "states": ["SC", "NC"],
            "counties": county_names,
            "maxItems": cap("probate_foreclosure_leads", default=250),
            "sp_intended_usage": "research",
            "sp_improvement_suggestions": "",
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=300)
        out: list[Listing] = []
        for it in items:
            href = it.get("sourceUrl") or it.get("url") or it.get("link")
            if not href:
                continue
            sale_date = None
            for k in ("eventDate", "saleDate", "auctionDate", "filingDate"):
                if it.get(k):
                    try:
                        sale_date = dateparser.parse(str(it[k]))
                        break
                    except (ValueError, TypeError):
                        pass
            event = (it.get("eventType") or "").lower().replace(" ", "_")
            ltype = EVENT_TYPE_MAP.get(event, ListingType.UNKNOWN)
            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=it.get("address") or it.get("streetAddress"),
                    city=it.get("city"),
                    state=it.get("state"),
                    zip_code=it.get("zip") or it.get("zipCode"),
                    county=(it.get("county") or "").replace(" County", "") or None,
                    parcel_id=it.get("parcelId") or it.get("apn"),
                    sale_date=sale_date,
                    opening_bid=it.get("openingBid") or it.get("startingBid") or it.get("amount"),
                    judgment_amount=it.get("debtAmount") or it.get("loanAmount"),
                    plaintiff=it.get("plaintiff") or it.get("creditor"),
                    defendant=it.get("defendant") or it.get("debtor"),
                    case_number=it.get("caseNumber"),
                    description=(it.get("description") or "")[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"jungle_synthesizer": it},
                )
            )
        return out
