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

SCOPE BUG FOUND AND FIXED (2026-10-03), same class as enrichment_comps.py's
c3edea94 fix and the bbb6f2f9 generic-distress widen. This scraper looped
``config.ALL_COUNTIES`` — the 18-county (11 NC + 7 SC) FLIP footprint from a
2026-05 scoping decision — querying each county by its SEAT TOWN. Most of
this scraper's output is NOT a flip: only REO/trustee-sale/foreclosure
keyword matches land on a _FLIP_LISTING_TYPES type (REO, FORECLOSURE_SALE);
tax-sale, estate/heir/probate and the generic "as-is/motivated seller" matches
land on TAX_SALE / LIS_PENDENS / DISTRESSED, all of which are distressed-type
leads admissible in any real NC/SC county per config.in_scope_distressed's
2026-09-15 mandate. Looping only the 18 footprint seats meant every one of
those non-flip matches outside the footprint could never be found at all, no
matter how permissive the downstream scope gate is.

Live-verified 2026-10-03 against the real HomeHarvest for_sale feed, querying
by COUNTY (not seat town) the same way the comps fix validated — counties
WAY outside the old 18 already carry real distress-keyword matches for free:
Catawba NC 34 matches / 1,091 for_sale, Mecklenburg NC 170 / 5,231, Richland
SC 114 / 2,318. Fix: loop every real NC/SC county (validation.py) and query
"<County> County, <ST>" — the format the comps fix proved resolves the whole
county, not just its seat, and needs no per-county seat gazetteer (which only
ever existed for the 18 footprint counties). Flip-type matches (REO,
FORECLOSURE_SALE) outside the 18 are still correctly dropped downstream by
main._flip_outside_footprint — this fix only stops DISCARDING the distressed-
type matches at the source before the scope gate ever sees them.

Cost note: this widens the loop from 18 to up to 146 counties (one HomeHarvest
call each, ~1-15s depending on county size — Mecklenburg's 5,231-row pull took
15s live). timeout_s is raised accordingly; see the class docstring.
"""
from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...validation import NC_COUNTIES as _NC_COUNTY_NAMES, SC_COUNTIES as _SC_COUNTY_NAMES

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


def _str(v):
    """A text value (pandas NaN / blank -> None)."""
    v = _clean(v)
    return str(v).strip() or None if v is not None else None


def _date_str(v):
    """YYYY-MM-DD of a date / Timestamp / ISO string (pandas NaT / NaN / blank -> None)."""
    v = _clean(v)
    if v is None:
        return None
    s = str(v).strip()
    return None if not s or s.lower() in ("nat", "nan", "none") else s[:10]


def _clean(v):
    # pandas NaN / empty -> None; pass strings + phone lists through unchanged
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


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

    # Found 2026-10-01 (national/reo per-source audit): this sibling scraper
    # (national.homeharvest) already fixed this exact gap -- alt_photos
    # (homeharvest's comma-separated extra-photo column) and office_email
    # were captured there but never backported here. Every row here was
    # shipping with only ever ONE photo and no office-level fallback email,
    # despite homeharvest's own dataframe already carrying both for free (no
    # extra request).
    photos: list[str] = []
    primary = row.get("primary_photo") or ""
    if primary and not (isinstance(primary, float) and primary != primary):
        photos.append(str(primary))
    extra_photos = row.get("alt_photos") or ""
    if isinstance(extra_photos, str) and extra_photos:
        # alt_photos is comma-separated; keep up to 5 more (6 total max).
        photos.extend([p.strip() for p in extra_photos.split(",") if p.strip()][:5])

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
        # estimated_value -> market_value, assessed_value -> tax_value (mirrors homeharvest.py:96-97)
        market_value=_num(row.get("estimated_value")),
        tax_value=_num(row.get("assessed_value")),
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
                "agent_name": _clean(row.get("agent_name")),
                "agent_email": _clean(row.get("agent_email")),
                "agent_phones": _clean(row.get("agent_phones")),
                "broker_name": _clean(row.get("broker_name")),
                "office_phones": _clean(row.get("office_phones")),
                "office_email": _clean(row.get("office_email")),
                "half_baths": _num(row.get("half_baths")),
                "tax": _num(row.get("tax")),  # annual property-tax $ (Realtor.com tax_history latest)
                # 2026-10-08 source-completeness audit: on the same HomeHarvest row, never kept.
                # Prior sale (price/date: equity and how long held), the unit (two units of one
                # building share a street line), the MLS ids, the pending and last status
                # change dates (a price cut or a fallen-through contract), HOA fee, stories.
                "unit": _str(row.get("unit")),
                "mls": _str(row.get("mls")),
                "mls_id": _str(row.get("mls_id")),
                "last_sold_date": _date_str(row.get("last_sold_date")),
                "last_sold_price": _num(row.get("last_sold_price")),
                "pending_date": _date_str(row.get("pending_date")),
                "last_status_change_date": _date_str(row.get("last_status_change_date")),
                "hoa_fee": _num(row.get("hoa_fee")),
                "stories": _num(row.get("stories")),
                "new_construction": (bool(row.get("new_construction"))
                                     if row.get("new_construction") in (True, False) else None),
            },
            "zillow": {
                "photo": photos[0] if photos else None,
                "photos": photos[:6],
            },
        },
    )


#: Every real NC/SC county (validation.py) -- widened 2026-10-03 from the
#: 18-county flip footprint. See the module docstring's SCOPE BUG note.
COUNTY_UNIVERSE: tuple[tuple[str, str], ...] = tuple(sorted(
    {("NC", c) for c in _NC_COUNTY_NAMES} | {("SC", c) for c in _SC_COUNTY_NAMES}
))


def _distress_location(county: str, state: str) -> str:
    """Location string for HomeHarvest's (Realtor.com) geo-suggest search.

    "<County> County, <ST>" resolves the WHOLE county, not just its seat town
    -- the same format enrichment_comps.py's 2026-10-03 fix verified live
    across every county size (Catawba NC, Greenville SC, rural Allendale SC),
    and this module's own module-docstring live-check confirms again here
    (Catawba 34 matches/1,091 for_sale, Mecklenburg 170/5,231, Richland SC
    114/2,318). Removes the need for a per-county seat-town gazetteer, which
    only ever existed for the old 18-county footprint.
    """
    return f"{county} County, {state}"


#: Optional list-date window in days (FORECLOSURE_DISTRESSED_PAST_DAYS); 0 / unset = every active
#: for-sale listing.
try:
    PAST_DAYS = int(os.environ.get("FORECLOSURE_DISTRESSED_PAST_DAYS") or 0)
except ValueError:
    PAST_DAYS = 0


def _scrape_county(state: str, county: str) -> list[Listing]:
    """Sync HomeHarvest pull → distress-match. Run in thread pool."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    out: list[Listing] = []
    try:
        # No past_days (2026-10-08): with past_days=120 HomeHarvest returns only listings put on
        # the market in the last 120 days, so a listing that has sat unsold longer (the most
        # motivated seller) was never read. Live, Polk County NC: 240 rows / 15 distress matches
        # with the window, 534 / 22 without; 3.8 s -> 7.1 s.
        kw = {"past_days": PAST_DAYS} if PAST_DAYS else {}
        df = scrape_property(
            location=_distress_location(county, state),
            listing_type="for_sale",
            **kw,
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
    # Widened 2026-10-03 from 18 counties to COUNTY_UNIVERSE (up to 146) -- see
    # module docstring. Measured live: a large urban county (Mecklenburg,
    # 5,231 for_sale rows) took ~15s; most of the other ~128 newly-added
    # counties are smaller/rural. Raised from 600s to budget for 8x the
    # county count, same "noticeably longer, budget more wall-clock" note
    # scripts/backfill_comps.py's docstring carries for its own 2026-10-03 widen.
    timeout_s = 1200.0

    async def fetch(self) -> Iterable[Listing]:
        loop = asyncio.get_event_loop()
        # Deduped by URL into self.partial as each county finishes (2026-10-08), so a soft
        # timeout ships every finished county instead of nothing.
        deduped = self.partial
        seen: set[str] = set()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                loop.run_in_executor(pool, _scrape_county, state, county)
                for state, county in COUNTY_UNIVERSE
            ]
            for fut in asyncio.as_completed(futures):
                try:
                    r = await fut
                except Exception:  # noqa: BLE001 - one county never sinks the rest
                    continue
                for li in r or []:
                    if li.source_url in seen:
                        continue
                    seen.add(li.source_url)
                    deduped.append(li)
        return list(deduped)
