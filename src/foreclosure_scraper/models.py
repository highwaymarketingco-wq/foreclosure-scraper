"""Unified listing schema."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class ListingType(str, Enum):
    FORECLOSURE_SALE = "foreclosure_sale"
    TAX_SALE = "tax_sale"
    TAX_LIEN = "tax_lien"
    LIS_PENDENS = "lis_pendens"
    REO = "reo"
    AUCTION = "auction"
    SHERIFF_SALE = "sheriff_sale"
    HOA_SALE = "hoa_sale"
    UNKNOWN = "unknown"


class PropertyKind(str, Enum):
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    MULTI_FAMILY = "multi_family"
    MOBILE = "mobile"
    COMMERCIAL = "commercial"
    LAND = "land"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Listing(BaseModel):
    """A single foreclosure / tax sale / lien listing, normalized."""

    # Source attribution
    source: str = Field(description="Slug of the scraper that produced this row")
    source_url: str = Field(description="Reachable link to the listing detail page")

    # Listing categorization
    listing_type: ListingType = ListingType.UNKNOWN
    property_kind: PropertyKind = PropertyKind.UNKNOWN

    # Location
    street_address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    county: str | None = None
    parcel_id: str | None = None
    legal_description: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    # Sale info
    sale_date: datetime | None = None
    sale_time: str | None = None
    sale_location: str | None = None
    opening_bid: float | None = None
    judgment_amount: float | None = None
    upset_bid_deadline: datetime | None = None
    auction_status: str | None = None  # active, postponed, withdrawn, cancelled

    # Parties
    plaintiff: str | None = None
    defendant: str | None = None
    trustee: str | None = None
    case_number: str | None = None

    # Property characteristics (best effort, often null)
    zoning: str | None = None
    acreage: float | None = None
    lot_size_sqft: float | None = None
    living_sqft: float | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None
    year_built: int | None = None
    assessed_value: float | None = None
    market_value: float | None = None
    tax_value: float | None = None
    description: str | None = None

    # Provenance
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    raw: dict[str, Any] = Field(default_factory=dict)

    def dedupe_key(self) -> str:
        """Stable key used to de-duplicate across sources."""
        if self.parcel_id:
            return f"parcel:{self.state or ''}:{self.parcel_id.strip().upper()}"
        if self.street_address and self.zip_code:
            return f"addr:{self.street_address.strip().lower()}|{self.zip_code.strip()}"
        if self.case_number and self.county:
            return f"case:{self.state or ''}:{self.county.lower()}:{self.case_number.strip().upper()}"
        return f"url:{self.source_url}"

    def display_address(self) -> str:
        bits = [
            self.street_address,
            ", ".join(b for b in (self.city, self.state) if b),
            self.zip_code,
        ]
        return " ".join(b for b in bits if b)

    def merge(self, other: "Listing") -> "Listing":
        """Merge another listing into this one, preferring non-null values."""
        out = self.model_copy(deep=True)
        for field_name in self.model_fields:
            if field_name in {"first_seen", "raw", "source", "source_url"}:
                continue
            current = getattr(out, field_name)
            new = getattr(other, field_name)
            if (current is None or current == "") and new not in (None, ""):
                setattr(out, field_name, new)
        out.last_seen = max(self.last_seen, other.last_seen)
        out.raw = {**self.raw, **other.raw}
        return out
