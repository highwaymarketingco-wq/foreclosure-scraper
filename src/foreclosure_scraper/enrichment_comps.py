"""Comp finder + property-data backfill via HomeHarvest sold listings.

For every foreclosure listing on the dashboard, this enrichment:
  1. Backfills missing sqft / beds / baths / year_built / lot_sqft from
     HomeHarvest's per-address property record
  2. Attaches 3 nearest sold comps that match by zip + sqft + beds
  3. Computes price-per-sqft from those comps so the calculator + grade can
     use real local market values, not statewide averages

Cost: $0. HomeHarvest hits Realtor.com's public API directly.

Strategy: pull all sold properties (past 180d) for each county seat ONCE per
run, build an in-memory pool keyed by ZIP, then look up each listing in O(1).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import structlog

from .config import ALL_COUNTIES
from .models import Listing

log = structlog.get_logger()


def _sold_pool_for_seat(seat: str, state: str) -> list[dict]:
    """Sync HomeHarvest pull of sold properties for one county seat."""
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
        return df.to_dict("records")
    except Exception as exc:
        log.debug("comps.sold_pool.error", seat=seat, state=state, error=str(exc)[:100])
        return []


def _rent_pool_for_seat(seat: str, state: str) -> list[dict]:
    """Pull rentals for cash-flow comps (free via HomeHarvest)."""
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


def _by_address_lookup(street: str, city: str, state: str, zip_code: str | None = None) -> dict | None:
    """Single-property lookup by full address. Used for backfill when a foreclosure
    came from a courthouse roster (case# + address but no specs)."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return None
    try:
        # Try the address as a single-location query
        loc = f"{street}, {city}, {state}"
        if zip_code:
            loc = f"{loc} {zip_code}"
        df = scrape_property(location=loc, listing_type="for_sale")
        if df is not None and len(df) > 0:
            return df.iloc[0].to_dict()
    except Exception:
        pass
    return None


def _num(v):
    try:
        if v is None or (isinstance(v, float) and (v != v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick_3_comps(target: Listing, sold_pool: list[dict]) -> list[dict]:
    """Pick 3 best comps for the target foreclosure.

    Match criteria (in order):
      1. Same ZIP code (or city if no ZIP)
      2. Within ±25% sqft (if both have sqft)
      3. Same bed count ±1 (if both have beds)
      4. Sorted by recency, then sqft proximity

    Returns up to 3 dicts with: {address, sold_price, sold_date, sqft, beds, baths, $/sqft}
    """
    if not sold_pool:
        return []

    target_zip = (target.zip_code or "").strip()
    target_city = (target.city or "").strip().lower()
    target_sqft = target.living_sqft
    target_beds = target.bedrooms

    # Stage 1: zip-match (fall back to city if no zip)
    if target_zip:
        candidates = [s for s in sold_pool if (str(s.get("zip_code") or "").strip()) == target_zip]
    else:
        candidates = [s for s in sold_pool
                      if (str(s.get("city") or "").strip().lower()) == target_city]

    if not candidates:
        # Last resort: city-level if zip-match failed
        candidates = [s for s in sold_pool
                      if (str(s.get("city") or "").strip().lower()) == target_city]

    # Stage 2: sqft band ±25% if target has sqft
    if target_sqft and len(candidates) > 5:
        lo, hi = target_sqft * 0.75, target_sqft * 1.25
        sqft_filt = [s for s in candidates if s.get("sqft") and lo <= float(s["sqft"]) <= hi]
        if len(sqft_filt) >= 3:
            candidates = sqft_filt

    # Stage 3: bed band ±1 if target has beds
    if target_beds and len(candidates) > 5:
        lo, hi = target_beds - 1, target_beds + 1
        bed_filt = [s for s in candidates
                    if s.get("beds") is not None and lo <= float(s["beds"]) <= hi]
        if len(bed_filt) >= 3:
            candidates = bed_filt

    # Sort by sold_date desc (most recent first), then by sqft proximity
    def score(s):
        sold_date = str(s.get("last_sold_date") or "")
        # ISO date sorts naturally; missing dates last
        date_key = sold_date or "0000-00-00"
        sqft_diff = abs(float(s.get("sqft") or 0) - (target_sqft or 0))
        return (-1 * (date_key,), sqft_diff)

    try:
        candidates.sort(key=lambda s: (str(s.get("last_sold_date") or "0000"), -1), reverse=True)
    except Exception:
        pass

    out: list[dict] = []
    for s in candidates[:3]:
        sold_price = _num(s.get("sold_price")) or _num(s.get("list_price"))
        sqft = _num(s.get("sqft"))
        out.append({
            "address": str(s.get("street") or s.get("formatted_address") or "").strip(),
            "city": s.get("city"),
            "zip": s.get("zip_code"),
            "sold_price": sold_price,
            "sold_date": str(s.get("last_sold_date") or "") or None,
            "sqft": sqft,
            "beds": _num(s.get("beds")),
            "baths": _num(s.get("full_baths")),
            "year_built": int(s["year_built"]) if s.get("year_built") and str(s["year_built"]).replace(".0", "").isdigit() else None,
            "price_per_sqft": round(sold_price / sqft, 2) if sold_price and sqft else None,
            "url": s.get("property_url"),
        })
    return out


def _backfill_property_data(li: Listing, sold_pool: list[dict]) -> None:
    """Try to find this listing's specs in the sold pool by address match.
    A foreclosure that recently sold (or was listed and pulled) might appear
    in HomeHarvest with full sqft/beds/baths even though our courthouse
    roster only had the address.
    """
    if not (li.street_address and (li.zip_code or li.city)):
        return
    target_street = li.street_address.strip().lower()
    for s in sold_pool:
        s_street = str(s.get("street") or "").strip().lower()
        if not s_street:
            continue
        if s_street == target_street or (s_street and s_street in target_street) or (target_street and target_street in s_street):
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


def _pick_3_rent_comps(target: Listing, rent_pool: list[dict]) -> list[dict]:
    """Pick 3 best rent comps. Same matching strategy as sold."""
    if not rent_pool:
        return []
    target_zip = (target.zip_code or "").strip()
    target_city = (target.city or "").strip().lower()
    target_sqft = target.living_sqft
    target_beds = target.bedrooms

    candidates = ([s for s in rent_pool if str(s.get("zip_code") or "").strip() == target_zip]
                  if target_zip
                  else [s for s in rent_pool if str(s.get("city") or "").strip().lower() == target_city])
    if not candidates:
        candidates = [s for s in rent_pool
                      if str(s.get("city") or "").strip().lower() == target_city]
    if target_beds and len(candidates) > 5:
        bed_filt = [s for s in candidates
                    if s.get("beds") is not None and abs(float(s["beds"]) - target_beds) <= 1]
        if len(bed_filt) >= 3:
            candidates = bed_filt
    if target_sqft and len(candidates) > 5:
        lo, hi = target_sqft * 0.75, target_sqft * 1.25
        sqft_filt = [s for s in candidates if s.get("sqft") and lo <= float(s["sqft"]) <= hi]
        if len(sqft_filt) >= 3:
            candidates = sqft_filt

    out: list[dict] = []
    for s in candidates[:3]:
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


async def enrich_with_comps(listings: list[Listing]) -> None:
    """Pull sold + rent pools per priority county-seat and attach:
       - 3 sold comps (for ARV calculation)
       - 3 rent comps (for cash-flow + cap rate)
       - Spec backfill (sqft, beds, baths, year)
    All free via HomeHarvest direct.
    """
    if not listings:
        return
    log.info("comps.start", count=len(listings))

    # Pull sold + rent pools for all counties in parallel
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=6) as pool:
        sold_futs = [loop.run_in_executor(pool, _sold_pool_for_seat, c.seat, c.state) for c in ALL_COUNTIES]
        rent_futs = [loop.run_in_executor(pool, _rent_pool_for_seat, c.seat, c.state) for c in ALL_COUNTIES]
        sold_results, rent_results = await asyncio.gather(
            asyncio.gather(*sold_futs, return_exceptions=True),
            asyncio.gather(*rent_futs, return_exceptions=True),
        )

    sold_pools: dict[tuple[str, str], list[dict]] = {}
    rent_pools: dict[tuple[str, str], list[dict]] = {}
    for c, sr, rr in zip(ALL_COUNTIES, sold_results, rent_results):
        if isinstance(sr, list):
            sold_pools[(c.state, c.name)] = sr
        if isinstance(rr, list):
            rent_pools[(c.state, c.name)] = rr
    total_sold = sum(len(p) for p in sold_pools.values())
    total_rent = sum(len(p) for p in rent_pools.values())
    log.info("comps.pools_built", counties=len(sold_pools),
             total_sold=total_sold, total_rent=total_rent)

    matched_sold = matched_rent = backfilled = 0
    for li in listings:
        if not (li.county and li.state):
            continue

        sold_pool = sold_pools.get((li.state, li.county))
        rent_pool = rent_pools.get((li.state, li.county))

        if sold_pool:
            before = (li.living_sqft, li.bedrooms, li.bathrooms)
            _backfill_property_data(li, sold_pool)
            after = (li.living_sqft, li.bedrooms, li.bathrooms)
            if before != after:
                backfilled += 1

            comps = _pick_3_comps(li, sold_pool)
            if comps:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["comps"] = comps
                ppsf = [c["price_per_sqft"] for c in comps if c.get("price_per_sqft")]
                if ppsf:
                    ppsf.sort()
                    li.raw["comp_median_ppsf"] = ppsf[len(ppsf) // 2]
                matched_sold += 1

        if rent_pool:
            rents = _pick_3_rent_comps(li, rent_pool)
            if rents:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["rent_comps"] = rents
                rpsf = [r["rent_per_sqft"] for r in rents if r.get("rent_per_sqft")]
                if rpsf:
                    rpsf.sort()
                    li.raw["rent_median_ppsf"] = rpsf[len(rpsf) // 2]
                # Estimate monthly rent for subject by median × subject sqft
                monthly = [r["rent_per_month"] for r in rents if r.get("rent_per_month")]
                if monthly:
                    monthly.sort()
                    li.raw["estimated_monthly_rent"] = monthly[len(monthly) // 2]
                matched_rent += 1

    log.info("comps.done", listings=len(listings),
             sold_matched=matched_sold, rent_matched=matched_rent,
             backfilled=backfilled)
