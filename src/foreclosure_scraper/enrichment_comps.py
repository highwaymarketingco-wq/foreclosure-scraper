"""Comp finder + property-data backfill via HomeHarvest sold listings.

Like-for-like comp matching for accurate ARV and cash-flow analysis. The matcher
filters by:
  1. Property kind (single-family / condo / townhouse / multi-family / land /
     manufactured) — never compares across kinds
  2. Style/quality bucket (manufactured-vs-stick-built; new-build vs vintage)
  3. Year built within ±15 years (era proxy for build quality / systems age)
  4. Living sqft within ±20% (size band)
  5. Bed count exact (±0; bedrooms drive resale and rent dollars)
  6. Same ZIP first; relax to same city only if zip-pool is too thin

Plus rent comps via the same matcher, and condition-tier inference from
description text (move-in / cosmetic / major / gut). The condition tier feeds
the calculator's rehab estimate so a "needs full reno" listing isn't priced
the same as a "move-in ready" one.

Cost: $0. HomeHarvest hits Realtor.com's public API directly.
"""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import structlog

from .config import ALL_COUNTIES
from .models import Listing, PropertyKind

log = structlog.get_logger()


# ---- Pools (sold + rent) ---------------------------------------------------

def _sold_pool_for_seat(seat: str, state: str) -> list[dict]:
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    try:
        df = scrape_property(
            location=f"{seat}, {state}",
            listing_type="sold",
            past_days=180,
        )
        if df is None or len(df) == 0:
            return []
        records = df.to_dict("records")
        # Dedupe — HomeHarvest can return the same sale twice (re-list, MLS dupes);
        # an un-deduped pool double-counts a sale in the median.
        seen: set = set()
        deduped = []
        for r in records:
            key = r.get("property_url") or (
                str(r.get("street") or ""), r.get("sold_price"), str(r.get("last_sold_date") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        return deduped
    except Exception as exc:
        log.debug("comps.sold_pool.error", seat=seat, state=state, error=str(exc)[:100])
        return []


def _rent_pool_for_seat(seat: str, state: str) -> list[dict]:
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    try:
        df = scrape_property(
            location=f"{seat}, {state}",
            listing_type="for_rent",
            past_days=90,
        )
        if df is None or len(df) == 0:
            return []
        return df.to_dict("records")
    except Exception as exc:
        log.debug("comps.rent_pool.error", seat=seat, state=state, error=str(exc)[:100])
        return []


# --- Market velocity: months-of-inventory -> per-listing holding period -----
SOLD_WINDOW_MONTHS = 6.0   # the sold pool's past_days=180 == 6 months


def _active_count_for_seat(seat: str, state: str) -> int:
    """Count current for-sale listings (the numerator of months-of-inventory)."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return 0
    try:
        df = scrape_property(location=f"{seat}, {state}", listing_type="for_sale")
        return 0 if df is None else int(len(df))
    except Exception as exc:
        log.debug("comps.active_pool.error", seat=seat, state=state, error=str(exc)[:100])
        return 0


def _months_of_inventory(active: int, sold: int) -> float | None:
    """MOI = active listings / monthly sold rate. None if no sold signal."""
    monthly_sold = sold / SOLD_WINDOW_MONTHS
    if monthly_sold <= 0:
        return None
    return round(active / monthly_sold, 1)


def _holding_months_from_moi(moi: float | None) -> int:
    """Map absorption to an exit-time estimate (carrying cost driver).
    <2mo seller's market -> fast flip; 2-6 balanced; >6 buyer's market -> slow."""
    if moi is None:
        return 6
    if moi < 2:
        return 4
    if moi <= 6:
        return 6
    return 9


def _num(v):
    try:
        if v is None or (isinstance(v, float) and (v != v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- Property-kind classification ------------------------------------------

def _classify_kind(row: dict | Listing) -> str:
    """Bucket a HomeHarvest row OR a Listing into one of:
       sfr | condo | townhouse | multi | land | manufactured | unknown"""
    if isinstance(row, Listing):
        # Use Listing's own classification
        pk = row.property_kind
        if pk == PropertyKind.SINGLE_FAMILY:
            return "sfr"
        if pk == PropertyKind.CONDO:
            return "condo"
        if pk == PropertyKind.TOWNHOUSE:
            return "townhouse"
        if pk == PropertyKind.MULTI_FAMILY:
            return "multi"
        if pk == PropertyKind.LAND:
            return "land"
        if pk == PropertyKind.MOBILE:
            return "manufactured"
        # Fall through to text heuristic when UNKNOWN
        text_blob = " ".join(filter(None, [
            row.description or "",
            (row.raw or {}).get("style", ""),
        ])).lower()
    else:
        # HomeHarvest dict row
        style = str(row.get("style") or "").lower()
        if "manufactured" in style or "mobile" in style:
            return "manufactured"
        if "single" in style:
            return "sfr"
        if "condo" in style:
            return "condo"
        if "town" in style:
            return "townhouse"
        if "multi" in style or "duplex" in style or "triplex" in style or "fourplex" in style:
            return "multi"
        if "land" in style or "lot" in style or "vacant" in style:
            return "land"
        text_blob = " ".join(str(row.get(k) or "") for k in ("text", "description", "style")).lower()

    # Text heuristics
    if any(k in text_blob for k in ("manufactured home", "mobile home", "double wide", "single wide", "doublewide", "singlewide")):
        return "manufactured"
    if any(k in text_blob for k in ("vacant land", "raw land", "buildable lot", "build site")):
        return "land"
    if any(k in text_blob for k in ("condominium", "condo unit")):
        return "condo"
    if "townhouse" in text_blob or "townhome" in text_blob:
        return "townhouse"
    if any(k in text_blob for k in ("duplex", "triplex", "fourplex", "multi-family", "multifamily", "5+ units")):
        return "multi"
    return "unknown"


# ---- Spec backfill (best-effort match by exact street) ---------------------

def _backfill_property_data(li: Listing, sold_pool: list[dict]) -> None:
    if not (li.street_address and (li.zip_code or li.city)):
        return
    target_street = li.street_address.strip().lower()
    for s in sold_pool:
        s_street = str(s.get("street") or "").strip().lower()
        if not s_street:
            continue
        if s_street == target_street or s_street in target_street or target_street in s_street:
            if li.living_sqft is None and s.get("sqft"):
                li.living_sqft = _num(s.get("sqft"))
            if li.bedrooms is None and s.get("beds"):
                li.bedrooms = _num(s.get("beds"))
            if li.bathrooms is None and s.get("full_baths"):
                li.bathrooms = _num(s.get("full_baths"))
            if li.year_built is None and s.get("year_built") and str(s["year_built"]).replace(".0", "").isdigit():
                li.year_built = int(s["year_built"])
            if li.lot_size_sqft is None and s.get("lot_sqft"):
                li.lot_size_sqft = _num(s.get("lot_sqft"))
            return


# ---- Strict comp matcher ---------------------------------------------------

SQFT_BAND_PCT = 0.20    # ±20% of subject sqft
YEAR_BAND = 15          # ±15 years
BED_BAND_EXACT = True   # bedrooms must match exactly
LAND_LOT_BAND_PCT = 0.50  # for land, ±50% acreage tolerance
# Geographic accuracy: when the subject has coordinates, comps must be
# within this radius. Prevents a rural subject from being valued against
# county-seat sales 20+ miles away (the "inaccurate comps" complaint).
COMP_RADIUS_MILES = 10.0


def _within_band(value: float, target: float, pct: float) -> bool:
    if not value or not target:
        return False
    return target * (1 - pct) <= value <= target * (1 + pct)


def _haversine_miles(lat1, lon1, lat2, lon2) -> float | None:
    """Great-circle distance in miles, or None if any coord is missing."""
    try:
        from math import asin, cos, radians, sin, sqrt
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 3958.8 * 2 * asin(min(1.0, sqrt(a)))


def _filter_by_kind(pool: list[dict], target_kind: str) -> list[dict]:
    """Keep only same-kind properties from the pool."""
    if target_kind == "unknown":
        # No kind info on subject — return SFR pool (most common, safest default)
        target_kind = "sfr"
    out: list[dict] = []
    for p in pool:
        pk = _classify_kind(p)
        if pk == target_kind:
            out.append(p)
        # SFR ↔ townhouse interchangeable when one is unknown
        elif target_kind == "sfr" and pk == "townhouse":
            out.append(p)
    return out


def _pick_3_comps(target: Listing, sold_pool: list[dict]) -> list[dict]:
    """Strict like-for-like comp matcher. Refuses to mix kinds.

    Returns up to 3 dicts. If pool can't produce a like-for-like match, returns
    fewer (or zero) — better to show "not enough comps" than misleading comps.
    """
    target_kind = _classify_kind(target)
    target_zip = (target.zip_code or "").strip()
    target_city = (target.city or "").strip().lower()
    target_state = (target.state or "").strip().upper()
    target_sqft = target.living_sqft
    target_beds = target.bedrooms
    target_year = target.year_built
    target_lot = target.lot_size_sqft

    # Stage 1: same kind only
    kind_pool = _filter_by_kind(sold_pool, target_kind)
    if not kind_pool:
        return []
    match_quality = "kind"

    # Stage 1.5: geographic gate. If the subject has coordinates, attach a
    # distance to every comp that has coordinates and keep only those within
    # COMP_RADIUS_MILES. This is the most accurate anchor — it stops a rural
    # subject from being compared against county-seat sales 20+ miles away.
    has_geo = target.latitude is not None and target.longitude is not None
    if has_geo:
        near = []
        for s in kind_pool:
            d = _haversine_miles(target.latitude, target.longitude,
                                 s.get("latitude"), s.get("longitude"))
            if d is not None and d <= COMP_RADIUS_MILES:
                s = {**s, "_distance_mi": round(d, 1)}
                near.append(s)
        if near:
            kind_pool = near
            match_quality = "kind+geo"

    # Stage 2: zip-match within same kind
    zip_pool = [s for s in kind_pool if str(s.get("zip_code") or "").strip() == target_zip] if target_zip else []
    pool = zip_pool if zip_pool else kind_pool
    if zip_pool:
        match_quality = "zip+kind" + ("+geo" if has_geo else "")
    elif target_city:
        city_pool = [s for s in kind_pool
                     if str(s.get("city") or "").strip().lower() == target_city
                     and str(s.get("state") or "").strip().upper() == target_state]
        if city_pool:
            pool = city_pool
            match_quality = "city+kind" + ("+geo" if has_geo else "")

    # Stage 3 (LAND ONLY): match by lot acreage band — sqft is meaningless for raw land
    if target_kind == "land" and target_lot:
        lot_filt = [s for s in pool
                    if s.get("lot_sqft") and _within_band(float(s["lot_sqft"]), target_lot, LAND_LOT_BAND_PCT)]
        if lot_filt:
            pool = lot_filt
            match_quality += "+lot"

    # Stage 4 (NON-LAND): sqft band
    if target_kind != "land" and target_sqft:
        sqft_filt = [s for s in pool
                     if s.get("sqft") and _within_band(float(s["sqft"]), target_sqft, SQFT_BAND_PCT)]
        if len(sqft_filt) >= 3:
            pool = sqft_filt
            match_quality += "+sqft"

    # Stage 5 (NON-LAND): beds exact
    if target_kind not in ("land", "multi") and target_beds:
        bed_filt = [s for s in pool
                    if s.get("beds") is not None and float(s["beds"]) == target_beds]
        if len(bed_filt) >= 3:
            pool = bed_filt
            match_quality += "+beds"

    # Stage 6: year ±15
    if target_year:
        yr_filt = [s for s in pool
                   if s.get("year_built") and abs(float(s["year_built"]) - target_year) <= YEAR_BAND]
        if len(yr_filt) >= 3:
            pool = yr_filt
            match_quality += "+era"

    # Condition parity: a gut/major-condition sale closed BELOW renovated retail,
    # so it understates ARV for a fixed-up subject. Drop those when 3+ retail-
    # grade comps remain. Non-land only.
    if target_kind != "land":
        retail = [s for s in pool
                  if _comp_condition_tier(str(s.get("text") or s.get("description") or "")) not in ("gut", "major")]
        if len(retail) >= 3:
            pool = retail
            match_quality += "+cond"

    # Sort: closest-first when we have distances, else most-recent-first.
    try:
        if has_geo and any(s.get("_distance_mi") is not None for s in pool):
            pool.sort(key=lambda s: (s.get("_distance_mi") if s.get("_distance_mi") is not None else 9e9))
        else:
            pool.sort(key=lambda s: str(s.get("last_sold_date") or "0000"), reverse=True)
    except Exception:
        pass

    # Honesty flag: when the only anchor was "kind" — no zip, no city, and no
    # geographic coordinates — the comps are county-wide, NOT local. Mark them
    # so ARV downstream treats them as low-confidence instead of presenting
    # far-away sales as comparable.
    geographically_anchored = ("geo" in match_quality) or ("zip" in match_quality) or ("city" in match_quality)

    out: list[dict] = []
    for s in pool[:3]:
        sold_price = _num(s.get("sold_price")) or _num(s.get("list_price"))
        sqft = _num(s.get("sqft"))
        out.append({
            "address": str(s.get("street") or s.get("formatted_address") or "").strip(),
            "city": s.get("city"),
            "zip": s.get("zip_code"),
            "sold_price": sold_price,
            "sold_date": str(s.get("last_sold_date") or "") or None,
            "sqft": sqft,
            "lot_sqft": _num(s.get("lot_sqft")),
            "beds": _num(s.get("beds")),
            "baths": _num(s.get("full_baths")),
            "year_built": int(s["year_built"]) if s.get("year_built") and str(s["year_built"]).replace(".0", "").isdigit() else None,
            "kind": _classify_kind(s),
            "distance_mi": s.get("_distance_mi"),
            "geo_anchored": geographically_anchored,
            "price_per_sqft": round(sold_price / sqft, 2) if sold_price and sqft else None,
            "url": s.get("property_url"),
            "match_quality": match_quality,
        })

    # Line-item adjustment grid (improved property only): adjust each comp toward
    # the subject and re-express on the SUBJECT's sqft. ARV uses the median
    # ADJUSTED $/sqft (see enrich loop) instead of raw $/sqft.
    if target_kind != "land" and target.living_sqft:
        raw_ppsfs = sorted(c["price_per_sqft"] for c in out if c.get("price_per_sqft"))
        base_ppsf = raw_ppsfs[len(raw_ppsfs) // 2] if raw_ppsfs else None
        if base_ppsf:
            for c, s in zip(out, pool[:3]):
                eff, adj = _adjust_comp(target, s, base_ppsf)
                if eff:
                    c["adjusted_ppsf"] = eff
                    c["adjustments"] = adj
    return out


def _pick_3_rent_comps(target: Listing, rent_pool: list[dict]) -> list[dict]:
    """Strict rent-comp matcher: same kind + zip + sqft band + beds."""
    target_kind = _classify_kind(target)
    if target_kind == "land":
        return []  # land doesn't rent

    kind_pool = _filter_by_kind(rent_pool, target_kind)
    if not kind_pool:
        return []

    target_zip = (target.zip_code or "").strip()
    target_city = (target.city or "").strip().lower()
    target_state = (target.state or "").strip().upper()
    target_sqft = target.living_sqft
    target_beds = target.bedrooms

    pool = ([s for s in kind_pool if str(s.get("zip_code") or "").strip() == target_zip]
            if target_zip else [])
    if not pool and target_city:
        pool = [s for s in kind_pool
                if str(s.get("city") or "").strip().lower() == target_city
                and str(s.get("state") or "").strip().upper() == target_state]
    if not pool:
        return []  # don't fall back — rent varies too much across counties

    if target_beds:
        bed_filt = [s for s in pool
                    if s.get("beds") is not None and float(s["beds"]) == target_beds]
        if len(bed_filt) >= 3:
            pool = bed_filt
    if target_sqft:
        sqft_filt = [s for s in pool
                     if s.get("sqft") and _within_band(float(s["sqft"]), target_sqft, SQFT_BAND_PCT)]
        if len(sqft_filt) >= 3:
            pool = sqft_filt

    out: list[dict] = []
    for s in pool[:3]:
        rent = _num(s.get("list_price"))
        sqft = _num(s.get("sqft"))
        out.append({
            "address": str(s.get("street") or "").strip(),
            "city": s.get("city"),
            "zip": s.get("zip_code"),
            "rent_per_month": rent,
            "sqft": sqft,
            "beds": _num(s.get("beds")),
            "baths": _num(s.get("full_baths")),
            "rent_per_sqft": round(rent / sqft, 2) if rent and sqft else None,
            "url": s.get("property_url"),
        })
    return out


# ---- Condition tier inference ---------------------------------------------

CONDITION_PATTERNS = {
    "move_in_ready": re.compile(
        r"\b(move[\s\-]?in\s+ready|recently\s+(?:renovated|updated|remodeled)|"
        r"new\s+(?:roof|hvac|kitchen|bath)|fully\s+(?:renovated|updated)|"
        r"pristine|turn[\s\-]?key|like\s+new)\b", re.I),
    "cosmetic": re.compile(
        r"\b(needs\s+(?:cosmetic|minor)\s+(?:work|updates|TLC)|"
        r"some\s+(?:cosmetic|minor)\s+(?:work|TLC)|paint|carpet)\b", re.I),
    "major": re.compile(
        r"\b(needs\s+(?:major|substantial|significant)\s+(?:work|repairs)|"
        r"fixer[\s\-]?upper|handyman\s+special|investor\s+special|"
        r"as[\s\-]?is(?:\s+condition)?|cash\s+only|"
        r"needs\s+TLC|requires\s+(?:work|repair))\b", re.I),
    "gut": re.compile(
        r"\b(complete\s+(?:gut|renovation)|tear[\s\-]?down|knockdown|"
        r"shell\s+only|down\s+to\s+studs|fire[\s\-]?damaged|"
        r"condemned|uninhabitable)\b", re.I),
}

# --- Appraisal-style line-item adjustment grid (free, pure-Python) ---------
# A raw $/sqft median treats a 1,000-sqft and a 2,500-sqft comp as identical
# value-per-foot; a pro adjusts each comp toward the subject. GLA is adjusted at
# a MARGINAL rate (a bigger house isn't worth proportionally more per foot), the
# rest at conventional paired-sale dollar amounts. Gross adjustment is capped at
# 25% of the comp price — beyond that the comp is too dissimilar to trust.
MARGINAL_GLA_FRAC = 0.40   # marginal $/sqft = 40% of the local whole-value ppsf
BATH_ADJ = 5000.0          # per full-bath difference
LOT_ADJ_PER_SQFT = 1.0     # per sqft of lot delta (conservative)
LOT_ADJ_CAP_FRAC = 0.10    # lot adjustment capped at 10% of comp price
YEAR_ADJ = 400.0           # per year of effective-age difference (newer worth more)
MAX_GROSS_ADJ_FRAC = 0.25  # appraisal rule: total adjustment <= 25% of comp price


def _comp_condition_tier(text: str) -> str | None:
    """Worst condition tier signalled by a comp's listing text (or None)."""
    if not text:
        return None
    for tier in ("gut", "major", "cosmetic", "move_in_ready"):
        if CONDITION_PATTERNS[tier].search(text):
            return tier
    return None


def _adjust_comp(target: Listing, s: dict, base_ppsf: float) -> tuple[float | None, dict | None]:
    """Adjust a comp's sold price toward the subject; return (effective $/sqft
    expressed on the SUBJECT's sqft, adjustments breakdown). None if unusable."""
    price = _num(s.get("sold_price")) or _num(s.get("list_price"))
    comp_sqft = _num(s.get("sqft"))
    tgt_sqft = target.living_sqft
    if not price or not comp_sqft or not tgt_sqft or comp_sqft <= 0 or tgt_sqft <= 0:
        return None, None
    adj: dict = {}
    if base_ppsf:
        adj["gla"] = round((tgt_sqft - comp_sqft) * (MARGINAL_GLA_FRAC * base_ppsf), -2)
    cb, tb = _num(s.get("full_baths")), target.bathrooms
    if cb is not None and tb is not None:
        adj["baths"] = round((tb - cb) * BATH_ADJ, -2)
    cl, tl = _num(s.get("lot_sqft")), target.lot_size_sqft
    if cl and tl:
        lot_cap = LOT_ADJ_CAP_FRAC * price
        adj["lot"] = round(max(-lot_cap, min(lot_cap, (tl - cl) * LOT_ADJ_PER_SQFT)), -2)
    cy, ty = _num(s.get("year_built")), target.year_built
    if cy and ty:
        adj["age"] = round((ty - cy) * YEAR_ADJ, -2)
    net = sum(adj.values())
    cap = MAX_GROSS_ADJ_FRAC * price
    capped_net = max(-cap, min(cap, net))
    adj["net"] = round(capped_net, -2)
    adj["capped"] = abs(capped_net - net) > 1
    effective_ppsf = round((price + capped_net) / tgt_sqft, 2)
    return effective_ppsf, adj


# Default condition by year-built bucket when no description signals
DEFAULT_CONDITION_BY_AGE = {
    # newer than 5 years → move-in ready unless told otherwise
    "new":     "move_in_ready",     # built within 5 years
    "modern":  "move_in_ready",     # 5-25 years
    "vintage": "cosmetic",          # 25-50 years
    "older":   "major",             # 50-80 years
    "ancient": "gut",               # 80+ years
}


def _condition_tier(li: Listing) -> str:
    """Return one of: move_in_ready, cosmetic, major, gut.

    Strongest signal first: explicit description keywords. Falls back to
    age-based default when description is silent. Distressed-source listings
    default at least to 'cosmetic' (motivated seller is a tell).
    """
    parts: list[str] = []
    if li.description:
        parts.append(str(li.description))
    raw = li.raw if isinstance(li.raw, dict) else {}
    distressed = raw.get("distressed") or {}
    kw = distressed.get("matched_keywords") if isinstance(distressed, dict) else None
    if isinstance(kw, list):
        parts.append(" ".join(str(k) for k in kw))
    elif isinstance(kw, str):
        parts.append(kw)
    text = " ".join(parts)

    # Most-severe-first match
    for tier in ("gut", "major", "cosmetic", "move_in_ready"):
        if CONDITION_PATTERNS[tier].search(text):
            return tier

    # Default by age — DO NOT auto-tag "gut" purely on age. Gut requires
    # explicit signals (fire damage, condemned, complete-gut text). Old
    # homes default to "major" rehab; only the description triggers gut.
    yb = li.year_built
    if yb:
        from datetime import datetime as _dt
        age = _dt.utcnow().year - yb
        if age < 10:
            return "move_in_ready"
        if age < 30:
            return "cosmetic"
        if age < 60:
            return "cosmetic"  # 30-60y still mostly cosmetic absent text signals
        return "major"           # 60+y default major (was overzealous gut)

    # Distressed source → at least cosmetic
    if li.source in ("national.distressed", "national.propwire"):
        return "cosmetic"

    return "cosmetic"  # safe middle


# ---- Main enrichment -------------------------------------------------------

async def enrich_with_comps(listings: list[Listing]) -> None:
    """Pull sold + rent pools per priority county-seat and attach:
       - 3 sold comps (kind+zip+sqft+beds+era matched)
       - 3 rent comps (kind+zip+beds+sqft matched)
       - Spec backfill (sqft, beds, baths, year)
       - Condition tier (move_in / cosmetic / major / gut)
    """
    if not listings:
        return
    log.info("comps.start", count=len(listings))

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=6) as pool:
        sold_futs = [loop.run_in_executor(pool, _sold_pool_for_seat, c.seat, c.state) for c in ALL_COUNTIES]
        rent_futs = [loop.run_in_executor(pool, _rent_pool_for_seat, c.seat, c.state) for c in ALL_COUNTIES]
        active_futs = [loop.run_in_executor(pool, _active_count_for_seat, c.seat, c.state) for c in ALL_COUNTIES]
        sold_results, rent_results, active_results = await asyncio.gather(
            asyncio.gather(*sold_futs, return_exceptions=True),
            asyncio.gather(*rent_futs, return_exceptions=True),
            asyncio.gather(*active_futs, return_exceptions=True),
        )

    sold_pools: dict[tuple[str, str], list[dict]] = {}
    rent_pools: dict[tuple[str, str], list[dict]] = {}
    velocity: dict[tuple[str, str], dict] = {}
    for c, sr, rr, ar in zip(ALL_COUNTIES, sold_results, rent_results, active_results):
        if isinstance(sr, list):
            sold_pools[(c.state, c.name)] = sr
        if isinstance(rr, list):
            rent_pools[(c.state, c.name)] = rr
        active = ar if isinstance(ar, int) else 0
        moi = _months_of_inventory(active, len(sr) if isinstance(sr, list) else 0)
        velocity[(c.state, c.name)] = {
            "moi": moi, "holding_months_est": _holding_months_from_moi(moi),
            "active": active, "sold_180d": len(sr) if isinstance(sr, list) else 0,
        }
    total_sold = sum(len(p) for p in sold_pools.values())
    total_rent = sum(len(p) for p in rent_pools.values())
    log.info("comps.pools_built", counties=len(sold_pools),
             total_sold=total_sold, total_rent=total_rent)

    matched_sold = matched_rent = backfilled = 0
    cond_counts = {"move_in_ready": 0, "cosmetic": 0, "major": 0, "gut": 0}

    for li in listings:
        sold_pool = sold_pools.get((li.state, li.county)) if (li.county and li.state) else None
        rent_pool = rent_pools.get((li.state, li.county)) if (li.county and li.state) else None

        # Spec backfill from same-county sold pool
        before = (li.living_sqft, li.bedrooms, li.bathrooms)
        if sold_pool:
            _backfill_property_data(li, sold_pool)
        after = (li.living_sqft, li.bedrooms, li.bathrooms)
        if before != after:
            backfilled += 1

        # Condition tier
        if not isinstance(li.raw, dict):
            li.raw = {}

        # Market velocity -> per-listing holding-period estimate (calc reads it).
        vel = velocity.get((li.state, li.county)) if (li.county and li.state) else None
        if vel:
            li.raw["market_velocity"] = vel
        tier = _condition_tier(li)
        li.raw["condition_tier"] = tier
        cond_counts[tier] = cond_counts.get(tier, 0) + 1

        # Sold comps (strict like-for-like; may return fewer than 3 or zero)
        if sold_pool:
            comps = _pick_3_comps(li, sold_pool)
            if comps:
                li.raw["comps"] = comps
                # Honesty gate: only derive ARV $/sqft from comps that are
                # geographically anchored (same zip / city / within radius).
                # County-wide "kind only" comps are kept in raw for
                # transparency but must NOT drive ARV — that was the
                # "inaccurate comps" failure mode.
                anchored = bool(comps and comps[0].get("geo_anchored"))
                if not anchored:
                    li.raw["comps_geo_warning"] = (
                        "comps are county-wide (no same-zip/city/nearby match) — "
                        "ARV from these is low confidence"
                    )
                # Prefer the line-item ADJUSTED $/sqft (comp adjusted toward the
                # subject); fall back to raw $/sqft where no grid was computed.
                ppsf = [(c.get("adjusted_ppsf") or c.get("price_per_sqft"))
                        for c in comps
                        if (c.get("adjusted_ppsf") or c.get("price_per_sqft"))]
                if ppsf and anchored:
                    ppsf.sort()
                    # Arms-length / distressed filter: drop comps whose $/sqft is
                    # far below the median — typically as-is/distressed sales that
                    # understate ARV for a renovated subject. Tightened to 0.70x
                    # and fires at 3+ comps (was 0.50x / 4+).
                    if len(ppsf) >= 3:
                        median = ppsf[len(ppsf) // 2]
                        clean_ppsf = [p for p in ppsf if p >= median * 0.70]
                        if len(clean_ppsf) >= 3:
                            ppsf = clean_ppsf
                    li.raw["comp_median_ppsf"] = ppsf[len(ppsf) // 2]
                matched_sold += 1
            else:
                li.raw["comps_note"] = (
                    f"no like-for-like comps in same kind ({_classify_kind(li)}) "
                    f"+ same zip/city pool"
                )

        # Rent comps (strict; same kind + zip)
        if rent_pool:
            rents = _pick_3_rent_comps(li, rent_pool)
            if rents:
                li.raw["rent_comps"] = rents
                rpsf = [r["rent_per_sqft"] for r in rents if r.get("rent_per_sqft")]
                if rpsf:
                    rpsf.sort()
                    median_rpsf = rpsf[len(rpsf) // 2]
                    li.raw["rent_median_ppsf"] = median_rpsf
                    # Sanity-bound the per-sqft estimate
                    median_rpsf = max(0.50, min(3.50, median_rpsf))
                    if li.living_sqft:
                        # Estimate rent from per-sqft (more reliable than absolute median)
                        li.raw["estimated_monthly_rent"] = round(median_rpsf * li.living_sqft, -1)
                matched_rent += 1

    log.info("comps.done", listings=len(listings),
             sold_matched=matched_sold, rent_matched=matched_rent,
             backfilled=backfilled, conditions=cond_counts)
