"""HomeHarvest distressed-property finder — catches listings that are NOT
flagged as foreclosure but read as foreclosure-adjacent in the description.

These keywords are the strongest "motivated seller" signals on Realtor.com:
  - estate sale / heir / probate
  - trustee sale
  - as-is / "as is condition"
  - cash only / cash buyer
  - motivated seller / must sell / quick close
  - REO / bank-owned / lender-owned
  - short sale
  - tax sale / tax deed
  - foreclosure pending / pre-foreclosure

We pull a wide for_sale net per county (no foreclosure filter) then text-match
the description and listing fields for these markers. Free, no Apify.
"""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...config import ALL_COUNTIES
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

DISTRESS_KEYWORDS = re.compile(
    r"\b("
    r"estate\s+sale|heir|probate|"
    r"trustee\s+sale|"
    r"as[\s\-]?is(?:\s+condition)?|"
    r"cash\s+only|cash\s+buyer|"
    r"motivated\s+seller|must\s+sell|"
    r"REO|bank[\s\-]?owned|lender[\s\-]?owned|"
    r"short\s+sale|"
    r"tax\s+sale|tax\s+deed|"
    r"pre[\s\-]?foreclosure|foreclos(?:ure)?\s+pending|"
    r"distressed|fixer[\s\-]?upper|investor\s+special|"
    r"handyman\s+special|sold\s+as\s+is"
    r")\b",
    re.I,
)


def _num(v):
    try:
        if v is None or (isinstance(v, float) and (v != v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _matches_distress(row: dict) -> tuple[bool, list[str]]:
    """Check listing text for distress signals. Returns (is_distressed, matched_keywords)."""
    text_fields = []
    for k in ("text", "description", "mls_status", "status", "style"):
        v = row.get(k)
        if v and not (isinstance(v, float) and v != v):
            text_fields.append(str(v))
    blob = " ".join(text_fields)
    matches = DISTRESS_KEYWORDS.findall(blob)
    if matches:
        return True, sorted({m.lower() for m in matches})
    return False, []


def _to_listing(row: dict, county: str, matches: list[str]) -> Listing | None:
    url = row.get("property_url") or row.get("permalink")
    if not url:
        return None

    # Determine listing type from matched keywords (best signal)
    matches_str = " ".join(matches)
    if "reo" in matches_str or "bank" in matches_str or "lender" in matches_str:
        ltype = ListingType.REO
    elif "tax" in matches_str:
        ltype = ListingType.TAX_SALE
    elif "trustee" in matches_str or "foreclos" in matches_str:
        ltype = ListingType.FORECLOSURE_SALE
    elif "estate" in matches_str or "heir" in matches_str or "probate" in matches_str:
        ltype = ListingType.LIS_PENDENS  # treat probate as pre-sale signal
    else:
        # As-is / cash only / motivated seller — distressed but not yet at
        # foreclosure stage. Tagged as DISTRESSED (post-MLS pre-foreclosure)
        # rather than UNKNOWN so the dashboard shows a meaningful type.
        # ListingType.UNKNOWN was rendering as "unknown" in the UI which
        # confused users — these are real distressed listings, just not
        # in formal foreclosure proceedings yet.
        ltype = ListingType.DISTRESSED if hasattr(ListingType, "DISTRESSED") else ListingType.LIS_PENDENS

    style = (row.get("style") or "").lower()
    kind = PropertyKind.UNKNOWN
    if "single" in style:
        kind = PropertyKind.SINGLE_FAMILY
    elif "condo" in style:
        kind = PropertyKind.CONDO
    elif "town" in style:
        kind = PropertyKind.TOWNHOUSE
    elif "multi" in style or "duplex" in style:
        kind = PropertyKind.MULTI_FAMILY
    elif "land" in style or "lot" in style:
        kind = PropertyKind.LAND

    photos: list[str] = []
    primary = row.get("primary_photo") or ""
    if primary and not (isinstance(primary, float) and primary != primary):
        photos.append(str(primary))

    return Listing(
        source="national.distressed",
        source_url=str(url),
        listing_type=ltype,
        property_kind=kind,
        street_address=str(row.get("street") or "").strip() or None,
        city=str(row.get("city") or "").strip() or None,
        state=(str(row.get("state") or "").strip() or None),
        zip_code=str(row.get("zip_code") or "").strip() or None,
        county=county,
        opening_bid=_num(row.get("list_price")),
        bedrooms=_num(row.get("beds")),
        bathrooms=_num(row.get("full_baths")),
        living_sqft=_num(row.get("sqft")),
        year_built=int(row["year_built"]) if row.get("year_built") and str(row["year_built"]).replace(".0", "").isdigit() else None,
        lot_size_sqft=_num(row.get("lot_sqft")),
        latitude=_num(row.get("latitude")),
        longitude=_num(row.get("longitude")),
        description=(str(row.get("text") or row.get("description") or "") or "")[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "distressed": {
                "matched_keywords": matches,
                "mls_status": row.get("mls_status"),
                "list_date": str(row.get("list_date") or "") or None,
                "days_on_mls": _num(row.get("days_on_mls")),
            },
            "zillow": {
                "photo": photos[0] if photos else None,
                "photos": photos[:6],
            },
        },
    )


def _scrape_county(seat: str, state: str, county: str) -> list[Listing]:
    """Sync HomeHarvest pull → distress-match. Run in thread pool."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    out: list[Listing] = []
    try:
        df = scrape_property(
            location=f"{seat}, {state}",
            listing_type="for_sale",
            past_days=120,
        )
        if df is None or len(df) == 0:
            return out
        for _, row in df.iterrows():
            d = row.to_dict()
            is_distress, matches = _matches_distress(d)
            if not is_distress:
                continue
            li = _to_listing(d, county, matches)
            if li:
                out.append(li)
    except Exception as exc:
        log.debug("distressed.county.error", county=county, state=state, error=str(exc)[:100])
    return out


class DistressedListings(BaseScraper):
    slug = "national.distressed"
    name = "Distressed listings (HomeHarvest with motivated-seller keyword filter)"
    category = "national_aggregator"
    expected_min_count = 5
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        loop = asyncio.get_event_loop()
        out: list[Listing] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                loop.run_in_executor(pool, _scrape_county, c.seat, c.state, c.name)
                for c in ALL_COUNTIES
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    out.extend(r)
        # Dedupe by URL
        seen: set[str] = set()
        deduped: list[Listing] = []
        for li in out:
            if li.source_url in seen:
                continue
            seen.add(li.source_url)
            deduped.append(li)
        return deduped
