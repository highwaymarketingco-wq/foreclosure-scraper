"""Propwire — distressed property leads with FULL data: pre-foreclosure, auction,
bank-owned, tax liens, equity, owner info, MLS data, tax records, vacant flag.

This is the highest-quality foreclosure data source in our pipeline. Per-record
cost is ~$0.007 but each record has 50+ fields including auction dates, owner
contact, equity %, lead-type flags. We hit it once a month.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable
from urllib.parse import quote

from dateutil import parser as dateparser

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...models import Listing, ListingType, PropertyKind

ACTOR = "memo23/propwire-leads-scraper"


def _kind(pt: str | None) -> PropertyKind:
    if not pt:
        return PropertyKind.UNKNOWN
    s = pt.lower()
    return {
        "sfr": PropertyKind.SINGLE_FAMILY,
        "condo": PropertyKind.CONDO,
        "mfh_2_to_4": PropertyKind.MULTI_FAMILY,
        "mfh_5_plus": PropertyKind.MULTI_FAMILY,
        "mobile": PropertyKind.MOBILE,
        "land": PropertyKind.LAND,
        "commercial": PropertyKind.COMMERCIAL,
    }.get(s, PropertyKind.UNKNOWN)


def _build_search_url(states: list[str], lead_types: list[str], property_types: list[str] | None = None) -> str:
    """Build a propwire.com /search URL with the right filter JSON."""
    locations = [
        {
            "searchType": "T",
            "state": s,
            "title": f"{'South Carolina' if s == 'SC' else 'North Carolina'}, USA",
            "stateName": "South Carolina" if s == "SC" else "North Carolina",
        }
        for s in states
    ]
    filters = {
        "locations": locations,
        "lead_type": lead_types,
    }
    if property_types:
        filters["property_type"] = property_types
    return f"https://propwire.com/search?filters={quote(json.dumps(filters))}"


class PropwireForeclosures(BaseScraper):
    slug = "national.propwire"
    name = "Propwire (preforeclosure / auction / REO / tax lien)"
    category = "national_aggregator"
    timeout_s = 720.0

    async def fetch(self) -> Iterable[Listing]:
        # Three searches: pre-foreclosures, active auctions, bank-owned (REO)
        search_urls = [
            _build_search_url(["SC", "NC"], ["preforeclosure"]),
            _build_search_url(["SC", "NC"], ["auction"]),
            _build_search_url(["SC", "NC"], ["bank_owned"]),
            _build_search_url(["SC", "NC"], ["lien_tax", "ultra_liens"]),
        ]
        run_input = {
            "startUrls": [{"url": u} for u in search_urls],
            "maxItems": cap("propwire", default=1500),
            "maxConcurrency": 10,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=600)

        out: list[Listing] = []
        for it in items:
            href = it.get("propertyUrl") or it.get("url") or it.get("propwireUrl")
            if not href:
                continue
            addr = it.get("address") or {}
            if not isinstance(addr, dict):
                addr = {}

            sale_date = None
            for k in ("auctionDate", "saleDate", "foreclosureAuctionDate", "trustee_sale_date"):
                if it.get(k):
                    try:
                        sale_date = dateparser.parse(str(it[k]))
                        break
                    except (ValueError, TypeError):
                        pass

            lead = (it.get("lead_type") or it.get("leadType") or "").lower()
            ltype = ListingType.FORECLOSURE_SALE
            if "preforeclosure" in lead or "pre-foreclos" in lead:
                ltype = ListingType.LIS_PENDENS
            elif "auction" in lead:
                ltype = ListingType.AUCTION
            elif "bank_owned" in lead or "reo" in lead:
                ltype = ListingType.REO
            elif "tax" in lead and "lien" in lead:
                ltype = ListingType.TAX_LIEN

            flags = []
            for f in ("vacant", "absentee_owner", "code_violation", "high_equity", "low_equity", "bankruptcy"):
                if it.get(f) or f in lead:
                    flags.append(f)

            raw = {k: it.get(k) for k in (
                "lead_type", "estimated_value", "equity", "equity_percent", "loanBalance",
                "lastSaleDate", "lastSalePrice", "yearBuilt", "lotSizeSqft", "livingAreaSqft",
                "ownerName", "ownerMailing", "auctionLocation", "trusteeOpeningBid",
                "mortgageAmount", "lenderName", "trusteeName", "caseNumber",
            ) if k in it}

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=_kind(it.get("property_type") or it.get("propertyType")),
                    street_address=addr.get("street") or it.get("streetAddress") or it.get("address1"),
                    city=addr.get("city") or it.get("city"),
                    state=addr.get("state") or it.get("state"),
                    zip_code=addr.get("zip") or it.get("zip") or it.get("zipCode"),
                    county=(it.get("county") or "").replace(" County", "") or None,
                    parcel_id=it.get("parcelId") or it.get("apn"),
                    sale_date=sale_date,
                    sale_location=it.get("auctionLocation") or it.get("saleLocation"),
                    opening_bid=it.get("trusteeOpeningBid") or it.get("openingBid"),
                    judgment_amount=it.get("loanBalance") or it.get("mortgageAmount"),
                    market_value=it.get("estimated_value") or it.get("estimatedValue"),
                    tax_value=it.get("taxAssessedValue"),
                    bedrooms=it.get("bedrooms") or it.get("beds"),
                    bathrooms=it.get("bathrooms") or it.get("baths"),
                    living_sqft=it.get("livingAreaSqft") or it.get("buildingSqft"),
                    year_built=it.get("yearBuilt"),
                    lot_size_sqft=it.get("lotSizeSqft"),
                    plaintiff=it.get("lenderName") or it.get("plaintiff"),
                    defendant=it.get("ownerName") or it.get("defendant"),
                    trustee=it.get("trusteeName"),
                    case_number=it.get("caseNumber"),
                    description=(it.get("description") or "")[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"propwire": raw, "flags": flags},
                )
            )
        return out
