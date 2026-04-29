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


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
    requires_apify = True
    expected_min_count = 200
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
            # Probe-confirmed: Propwire returns no `url` field. Build one from `id`.
            pid = it.get("id") or it.get("property_id") or it.get("propertyId")
            href = it.get("propertyUrl") or it.get("url") or it.get("propwireUrl")
            if not href and pid:
                href = f"https://propwire.com/properties/{pid}"
            if not href:
                continue

            # Probe-confirmed: address is nested {address, city, state, zip}
            addr = it.get("address") or {}
            if not isinstance(addr, dict):
                addr = {}

            sale_date = None
            for k in ("auction_date", "auctionDate", "trustee_sale_date", "saleDate", "foreclosure_auction_date"):
                if it.get(k):
                    try:
                        sale_date = dateparser.parse(str(it[k]))
                        break
                    except (ValueError, TypeError):
                        pass

            # Probe-confirmed: lead_type is a DICT of booleans like
            # {"preforeclosure": true, "auction": false, "bank_owned": false, ...}
            lt_raw = it.get("lead_type") or it.get("leadType") or {}
            if isinstance(lt_raw, dict):
                active_flags = {k for k, v in lt_raw.items() if v}
            elif isinstance(lt_raw, list):
                active_flags = set(lt_raw)
            elif isinstance(lt_raw, str):
                active_flags = {lt_raw}
            else:
                active_flags = set()

            ltype = ListingType.FORECLOSURE_SALE
            if "preforeclosure" in active_flags:
                ltype = ListingType.LIS_PENDENS
            elif "auction" in active_flags:
                ltype = ListingType.AUCTION
            elif "bank_owned" in active_flags:
                ltype = ListingType.REO
            elif "lien_tax" in active_flags or "ultra_liens" in active_flags:
                ltype = ListingType.TAX_LIEN

            flags = sorted(active_flags & {
                "vacant_home", "vacant_lot", "absentee_owner", "code_violation",
                "high_equity", "low_equity", "negative_equity", "bankruptcy",
                "out_of_state_owner", "tired_landlord", "zombie_property", "free_and_clear",
            })

            raw = {k: it.get(k) for k in (
                "lead_type", "estimated_value", "estimated_equity", "estimated_equity_percentage",
                "last_sold_date", "last_sold_price", "year_built", "lot_size_sf", "building_area_sf",
                "owner_name", "owner_mailing_address", "auction_location", "trustee_opening_bid",
                "mortgage_amount", "lender_name", "trustee_name", "case_number",
                "mls_details", "geo_location",
            ) if k in it}

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=_kind(it.get("property_type") or it.get("propertyType")),
                    street_address=addr.get("address") or addr.get("street"),  # Propwire uses 'address' for street
                    city=addr.get("city"),
                    state=addr.get("state"),
                    zip_code=addr.get("zip") or addr.get("zipCode"),
                    county=(it.get("county") or "").replace(" County", "") or None,
                    parcel_id=it.get("parcel_id") or it.get("parcelId") or it.get("apn"),
                    sale_date=sale_date,
                    sale_location=it.get("auction_location") or it.get("auctionLocation"),
                    opening_bid=it.get("trustee_opening_bid") or it.get("opening_bid"),
                    judgment_amount=it.get("loan_balance") or it.get("mortgage_amount"),
                    market_value=it.get("estimated_value"),
                    tax_value=it.get("tax_assessed_value"),
                    bedrooms=it.get("bedrooms"),
                    bathrooms=it.get("bathrooms"),
                    living_sqft=it.get("building_area_sf"),
                    year_built=it.get("year_built"),
                    lot_size_sqft=it.get("lot_size_sf"),
                    plaintiff=it.get("lender_name"),
                    defendant=it.get("owner_name"),
                    trustee=it.get("trustee_name"),
                    case_number=it.get("case_number"),
                    description=(it.get("description") or "")[:500] or None,
                    latitude=_to_float((it.get("geo_location") or {}).get("latitude") if isinstance(it.get("geo_location"), dict) else None),
                    longitude=_to_float((it.get("geo_location") or {}).get("longitude") if isinstance(it.get("geo_location"), dict) else None),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"propwire": raw, "flags": flags},
                )
            )
        return out
