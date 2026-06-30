"""Unified listing schema."""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


# Street-suffix abbreviations used in _normalize_addr. The same street
# can appear as 'Main Street', 'Main St', 'Main St.', 'MAIN STREET' across
# sources — collapse to a canonical short form for dedupe matching.
_ADDR_SUFFIX_MAP = {
    "street": "st", "st.": "st",
    "avenue": "ave", "ave.": "ave",
    "road": "rd", "rd.": "rd",
    "drive": "dr", "dr.": "dr",
    "lane": "ln", "ln.": "ln",
    "court": "ct", "ct.": "ct",
    "boulevard": "blvd", "blvd.": "blvd",
    "highway": "hwy", "hwy.": "hwy",
    "place": "pl", "pl.": "pl",
    "circle": "cir", "cir.": "cir",
    "trail": "trl", "trl.": "trl",
    "parkway": "pkwy", "pkwy.": "pkwy",
    "terrace": "ter", "ter.": "ter",
    "way": "way",  # already short, but listed for explicitness
    "north": "n", "n.": "n",
    "south": "s", "s.": "s",
    "east": "e", "e.": "e",
    "west": "w", "w.": "w",
    "northeast": "ne", "ne.": "ne",
    "northwest": "nw", "nw.": "nw",
    "southeast": "se", "se.": "se",
    "southwest": "sw", "sw.": "sw",
}

# Unit indicators stripped from addresses before comparison — "123 Main
# St Apt 5" should match "123 Main St" since the unit isn't a separate
# parcel for foreclosure purposes (the building is foreclosed whole).
_UNIT_RE = re.compile(
    r"\s+(?:apt|apartment|unit|suite|ste|#|lot)\.?\s*[\w-]+\s*$",
    re.IGNORECASE,
)


def _normalize_addr(addr: str | None) -> str:
    """Canonical lowercase address string for dedupe. Expands suffixes
    (Street→st), strips unit indicators, collapses whitespace + commas."""
    if not addr:
        return ""
    s = addr.strip().lower()
    # Strip trailing unit indicators
    s = _UNIT_RE.sub("", s)
    # Strip city/state/zip suffix if present (commas suggest these)
    if "," in s:
        s = s.split(",", 1)[0]
    # Token-level suffix expansion
    tokens = []
    for tok in s.split():
        tok_clean = tok.rstrip(".")
        tokens.append(_ADDR_SUFFIX_MAP.get(tok, _ADDR_SUFFIX_MAP.get(tok_clean, tok_clean)))
    return " ".join(t for t in tokens if t)


def _normalize_parcel(parcel: str | None) -> str:
    """Strip every non-alphanumeric char, lowercase. So
    '1234-56-7890', '1234567890', '1234-56-7890.000' all collapse to
    '1234567890' (with the trailing '000' on variants that have it —
    still close enough that the second collapse rule below catches it)."""
    if not parcel:
        return ""
    s = re.sub(r"[^a-zA-Z0-9]", "", parcel).lower()
    # County GIS exports pad a base 10-digit PIN with trailing zeros out to 12 or 15 digits
    # (9678774126 -> 967877412600000). When EVERYTHING past the 10th char is zeros, the
    # 10-digit form is canonical, so the padded + bare copies collapse to one dedupe key.
    # Conservative: only strips a pure-zero pad, never significant digits.
    if len(s) > 10 and set(s[10:]) <= {"0"}:
        s = s[:10]
    elif len(s) > 10 and s.endswith("000"):   # legacy '.000' suffix on 11-13 digit variants
        s = s[:-3]
    return s


def _deep_merge_dict(a: dict, b: dict) -> dict:
    """Recursive dict merge. b's values win on leaf collisions, but
    nested dicts are merged (not overwritten).

    Used by Listing.merge() so that e.g. raw["gis"]["roof"] survives
    when other.raw["gis"] sets a different subkey like "year_built".
    Pre-fix, the shallow merge `{**self.raw, **other.raw}` wiped the
    entire raw["gis"] dict whenever both sides had something under it.
    """
    if not isinstance(a, dict):
        return b if isinstance(b, dict) else (b if b is not None else a)
    if not isinstance(b, dict):
        return a
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            # Prefer non-None over None
            if v is not None or k not in out:
                out[k] = v
    return out


def _normalize_case(case: str | None) -> str:
    """Strip every non-alphanumeric char, lowercase. So '24 SP 123',
    '24-SP-123', '24SP123', '2024-SP-00123' → '24sp123' / '2024sp00123'.

    Note: '24sp123' and '2024sp00123' still don't match — they're truly
    different year representations and stripped-zero issues. Leave as-is
    since a 2-vs-4-digit year mismatch could indicate different decades."""
    if not case:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", case).lower()


class ListingType(str, Enum):
    FORECLOSURE_SALE = "foreclosure_sale"
    TAX_SALE = "tax_sale"
    TAX_LIEN = "tax_lien"
    LIS_PENDENS = "lis_pendens"
    BANKRUPTCY = "bankruptcy"   # federal BK filing — a debtor-name distress signal, NOT a property listing
    REO = "reo"
    AUCTION = "auction"
    SHERIFF_SALE = "sheriff_sale"
    HOA_SALE = "hoa_sale"
    # DISTRESSED = motivated-seller / as-is / cash-only listings flagged via
    # description keywords on Realtor.com. Pre-foreclosure signal that hasn't
    # yet entered formal foreclosure proceedings.
    DISTRESSED = "distressed"
    # DIVORCE_NOTICE = service-by-publication divorce summons published
    # in NC Press Association legal notices. Motivated-seller signal —
    # contested divorces often force a property sale to divide assets.
    DIVORCE_NOTICE = "divorce_notice"
    # PROBATE_NOTICE = legally-required Notice to Creditors / Estate
    # filings published when an estate opens. Heirs typically want
    # to liquidate property fast (avoid carrying costs, split inheritance).
    PROBATE_NOTICE = "probate_notice"
    # ESTATE_LEAD = derived from obituary cross-reference: deceased
    # name matched against tax-record owner names. Property may not
    # yet be in formal probate but heirs are likely the new owners.
    ESTATE_LEAD = "estate_lead"
    # ELDERLY_DISABLED = owner carries a statutory age/disability property-tax
    # exemption (ELD 65+ / DIS totally-disabled / BLD blind / VET disabled-vet).
    # Property-keyed motivated-seller prospect (downsizing / can't maintain / heirs).
    ELDERLY_DISABLED = "elderly_disabled"
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
    redemption_deadline: datetime | None = None  # SC tax sale: sale_date + ~12mo (SC Code 12-51-90)
    foreclosure_process: str | None = None  # power_of_sale (NC) | judicial (SC) | tax

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
    living_sqft_estimated: bool = False  # True when living_sqft is a footprint×stories ESTIMATE
    bedrooms: float | None = None
    bathrooms: float | None = None
    year_built: int | None = None
    assessed_value: float | None = None
    market_value: float | None = None
    tax_value: float | None = None
    owner_name: str | None = None  # GIS-backfilled record owner (enrichment_gis_attrs)
    land_use: str | None = None    # GIS land-use / property-class string
    description: str | None = None

    # Provenance
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    raw: dict[str, Any] = Field(default_factory=dict)

    def dedupe_key(self) -> str:
        """Stable key used to de-duplicate across sources.

        Normalization rules (added per H3 fix 2026-05-08):
          - parcel: lowercase + strip every non-alnum char (so
            "1234-56-7890", "1234567890", "1234-56-7890.000" collapse).
            County included since parcel "1234" can collide across counties.
          - address: lowercase, expand common street-suffix abbreviations
            ('Street'→'st', 'Avenue'→'ave', etc.), collapse whitespace.
            zip optional — falls back to county+state when zip absent
            (most pre-enrich listings have no zip).
          - case_number: lowercase + strip non-alnum (so "24 SP 123",
            "24-SP-123", "24SP123", "2024-SP-00123" all collapse).
        """
        # parcel branch (strongest signal)
        if self.parcel_id and self.parcel_id.strip():
            p = _normalize_parcel(self.parcel_id)
            if p:
                county_part = (self.county or "").strip().lower()
                return f"parcel:{self.state or ''}:{county_part}:{p}"

        # address branch (with or without zip)
        if self.street_address and self.street_address.strip():
            addr = _normalize_addr(self.street_address)
            if addr:
                zip_part = (self.zip_code or "").strip()[:5]
                if zip_part:
                    return f"addr:{addr}|{zip_part}"
                # No zip — fall back to county+state which is usually
                # filled even pre-enrich.
                county_part = (self.county or "").strip().lower()
                if county_part:
                    return f"addr:{addr}|{self.state or ''}:{county_part}"

        # case_number + county branch
        if (self.case_number and self.case_number.strip()
                and self.county and self.county.strip()):
            c = _normalize_case(self.case_number)
            if c:
                return f"case:{self.state or ''}:{self.county.strip().lower()}:{c}"

        return f"url:{self.source_url}"

    def display_address(self) -> str:
        bits = [
            self.street_address,
            ", ".join(b for b in (self.city, self.state) if b),
            self.zip_code,
        ]
        return " ".join(b for b in bits if b)

    def merge(self, other: "Listing") -> "Listing":
        """Merge another listing into this one, preferring non-null values.

        M1 fix (2026-05-08):
          - Numeric monetary fields (opening_bid, tax_value, judgment_amount,
            arv, etc.) treat 0/0.0 as falsy. Pre-fix, a scraper that wrote
            opening_bid=0.0 (before validation cleared it) blocked a real
            bid from filling on merge.
          - first_seen = min(self.first_seen, other.first_seen) so the
            earliest sighting is preserved across merges.
          - raw is deep-merged instead of shallow — preserves nested
            subkeys (raw["gis"]["roof"] survives when other.raw["gis"]
            sets different subkeys).
          - Multi-source attribution: every source slug + URL the listing
            has been seen at is recorded in raw["also_seen_in"]. The
            primary source/source_url remain on self for compatibility,
            but dashboard popouts can read also_seen_in to show all
            attributions (e.g. "brock_scott + nc_ecourts").
        """
        out = self.model_copy(deep=True)

        # Fields where 0 should be treated as missing (validation may
        # later overwrite, but during merge we shouldn't preserve a
        # bogus zero over a real value).
        _MONEY_FIELDS = {
            "opening_bid", "tax_value", "judgment_amount",
            "estimated_value", "arv", "estimated_repair_cost",
        }

        def _is_falsy_for_merge(field_name: str, value) -> bool:
            if value is None:
                return True
            if value == "":
                return True
            if field_name in _MONEY_FIELDS and value == 0:
                return True
            return False

        for field_name in self.model_fields:
            if field_name in {"first_seen", "last_seen", "raw",
                              "source", "source_url"}:
                continue
            current = getattr(out, field_name)
            new = getattr(other, field_name)
            if _is_falsy_for_merge(field_name, current) and \
                    not _is_falsy_for_merge(field_name, new):
                setattr(out, field_name, new)

        # Provenance: keep earliest first_seen, latest last_seen
        out.first_seen = min(self.first_seen, other.first_seen)
        out.last_seen = max(self.last_seen, other.last_seen)

        # Deep-merge raw (preserves nested subkeys instead of clobbering)
        out.raw = _deep_merge_dict(self.raw, other.raw)

        # Multi-source attribution — keep EVERY source AND its link so the operator can open each
        # source for one property (e.g. ROD + assessor + law-firm), instead of hunting them down
        # by hand. Stored as {source, url} dicts; the primary stays on source/source_url.
        seen = [d for d in (out.raw.get("also_seen_in") or []) if isinstance(d, dict)]

        def _add(src, url):
            if not url or url == out.source_url:
                return  # primary link already lives on source_url
            if not any(d.get("url") == url for d in seen):
                seen.append({"source": src, "url": url})

        _add(other.source, other.source_url)
        for d in (other.raw.get("also_seen_in") or []):
            if isinstance(d, dict):
                _add(d.get("source"), d.get("url"))
        if seen:
            out.raw["also_seen_in"] = seen
        return out
