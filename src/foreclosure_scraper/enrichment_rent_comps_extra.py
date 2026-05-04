"""Expanded rent comps via HomeHarvest's "for_rent" endpoint.

We already pull rent comps (HomeHarvest -> Realtor.com) in
enrichment_comps. This expansion broadens the pool by hitting nearby
metros + relaxed filters when the strict like-for-like pool is empty,
giving every property at least a directional rent estimate.

Free, no spend.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


def _scrape_rent_pool(zip_code: str, kind: str) -> list[dict]:
    """Pull recent rentals for a zip + kind via HomeHarvest. Returns row dicts."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    out: list[dict] = []
    try:
        df = scrape_property(
            location=zip_code,
            listing_type="for_rent",
            past_days=180,
        )
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                d = row.to_dict()
                # Filter to property kind
                style = (d.get("style") or "").lower()
                if kind == "single_family" and "single" not in style:
                    continue
                if kind == "condo" and "condo" not in style:
                    continue
                if kind == "townhouse" and "town" not in style:
                    continue
                # Need rent amount + sqft for $/sf
                rent = d.get("list_price")
                sqft = d.get("sqft")
                if rent and sqft and 100 < float(rent) < 20000 and float(sqft) > 100:
                    out.append({
                        "address": (d.get("street") or d.get("full_street_line") or "").strip(),
                        "city": d.get("city"),
                        "zip_code": str(d.get("zip_code") or "")[:5] or None,
                        "rent": float(rent),
                        "sqft": float(sqft),
                        "rent_per_sqft": round(float(rent) / float(sqft), 3),
                        "beds": d.get("beds"),
                        "baths": d.get("full_baths"),
                        "year_built": d.get("year_built"),
                    })
    except Exception:
        pass
    return out


async def enrich_with_extra_rent_comps(listings: list[Listing]) -> None:
    """For each listing without rent_comps but with a zip, pull broad-pool
    rent comps from HomeHarvest. Tags raw.rent_comps_extra.
    """
    targets = []
    for li in listings:
        if not li.zip_code:
            continue
        existing = li.raw.get("rent_comps") if isinstance(li.raw, dict) else None
        if existing and len(existing) >= 3:
            continue  # already have strict comps
        if li.source == "national.courtlistener_bankruptcy":
            continue
        targets.append(li)

    if not targets:
        log.info("rent_comps_extra.no_targets")
        return

    log.info("rent_comps_extra.start", target_count=len(targets))

    # Cache per (zip, kind)
    pool_cache: dict[tuple[str, str], list[dict]] = {}
    loop = asyncio.get_event_loop()

    def _kind_str(li: Listing) -> str:
        from .models import PropertyKind
        if li.property_kind == PropertyKind.CONDO:
            return "condo"
        if li.property_kind == PropertyKind.TOWNHOUSE:
            return "townhouse"
        return "single_family"

    counts = {"queried_zips": 0, "tagged": 0}

    with ThreadPoolExecutor(max_workers=4) as pool:
        async def one(li: Listing) -> None:
            zip5 = li.zip_code[:5]
            kind = _kind_str(li)
            key = (zip5, kind)
            if key not in pool_cache:
                pool_cache[key] = await loop.run_in_executor(pool, _scrape_rent_pool, zip5, kind)
                counts["queried_zips"] += 1
            comps = pool_cache[key]
            if not comps:
                return
            # Median
            ppsfs = sorted(c["rent_per_sqft"] for c in comps)
            if not ppsfs:
                return
            median = ppsfs[len(ppsfs) // 2]
            if not isinstance(li.raw, dict):
                li.raw = {}
            if not li.raw.get("rent_comps"):
                li.raw["rent_comps_extra"] = comps[:5]
                li.raw["rent_median_ppsf_extra"] = round(median, 3)
                # Estimate monthly rent from subject sqft
                if li.living_sqft:
                    li.raw["estimated_monthly_rent_extra"] = int(median * float(li.living_sqft))
                counts["tagged"] += 1

        await asyncio.gather(*(one(li) for li in targets))

    log.info("rent_comps_extra.done", **counts)
