"""RentCast API integration — authoritative AVM + comparables + rent estimate.

RentCast is the property-data backend that DealCheck uses internally, so
this gives us the same source of truth at the API level.

Strategy:
  * Compute internal grade for ALL listings (free, fast).
  * Pick top-N listings by internal overall_score (default 100).
  * For each top-N listing, hit RentCast for AVM + comparables.
  * Merge RentCast AVM into the listing as a second valuation signal.
  * Update grade using the (weighted) average of internal + RentCast ARV.

Endpoints used:
  GET /avm/value?address={addr}         — Sale AVM (price, rangeLow, rangeHigh, comparables)
  GET /avm/rent/long-term?address={addr} — Rent AVM (rent, rangeLow, rangeHigh)

Auth: header `X-Api-Key: <key>`.
Quota: free tier 50/mo, Foundation $74/mo for 1000.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from ..http_client import client
from ..models import Listing

log = structlog.get_logger()

BASE_URL = "https://api.rentcast.io/v1"


def _api_key() -> str | None:
    return os.environ.get("RENTCAST_API_KEY") or None


def _build_address(li: Listing) -> str | None:
    if not li.street_address:
        return None
    bits = [li.street_address]
    if li.city:
        bits.append(li.city)
    if li.state and li.zip_code:
        bits.append(f"{li.state} {li.zip_code}")
    elif li.state:
        bits.append(li.state)
    return ", ".join(bits)


async def _call(c, path: str, params: dict, key: str) -> dict | None:
    try:
        r = await c.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={"X-Api-Key": key, "Accept": "application/json"},
            timeout=20.0,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            log.debug("rentcast.no_match", path=path, address=params.get("address"))
            return None
        log.warning("rentcast.error", status=r.status_code, path=path, body=r.text[:160])
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("rentcast.exception", error=str(exc)[:120])
        return None


async def avm_value(c, address: str, key: str) -> dict | None:
    return await _call(c, "/avm/value", {"address": address}, key)


async def avm_rent(c, address: str, key: str) -> dict | None:
    return await _call(c, "/avm/rent/long-term", {"address": address}, key)


def _apply_to_listing(li: Listing, value_payload: dict | None, rent_payload: dict | None) -> dict:
    """Merge RentCast results into the listing's raw and return a summary dict."""
    summary: dict[str, Any] = {}
    if value_payload:
        rc = {
            "avm_price": value_payload.get("price"),
            "avm_low": value_payload.get("priceRangeLow") or value_payload.get("rangeLow"),
            "avm_high": value_payload.get("priceRangeHigh") or value_payload.get("rangeHigh"),
            "comparables_count": len(value_payload.get("comparables") or []),
            "comparables": [
                {
                    "address": c.get("formattedAddress") or c.get("address"),
                    "price": c.get("price") or c.get("salePrice"),
                    "sale_date": c.get("removedDate") or c.get("saleDate"),
                    "distance_mi": c.get("distance"),
                    "sqft": c.get("squareFootage"),
                    "beds": c.get("bedrooms"),
                    "baths": c.get("bathrooms"),
                    "year_built": c.get("yearBuilt"),
                }
                for c in (value_payload.get("comparables") or [])[:5]
            ],
        }
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("rentcast", {}).update(rc)
        summary.update(rc)
    if rent_payload:
        rent = {
            "rent_avm": rent_payload.get("rent"),
            "rent_low": rent_payload.get("rentRangeLow") or rent_payload.get("rangeLow"),
            "rent_high": rent_payload.get("rentRangeHigh") or rent_payload.get("rangeHigh"),
        }
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("rentcast", {}).update(rent)
        summary.update(rent)
    return summary


def _internal_score(li: Listing) -> int:
    """Pick by overall_score from internal grading; if missing, use ROI/bid-to-arv."""
    g = (li.raw or {}).get("grade") if isinstance(li.raw, dict) else None
    if g and isinstance(g, dict):
        return int(g.get("overall_score") or 0)
    # Fallback: use calc.roi_pct (clamped) so unranked listings aren't all 0
    c = (li.raw or {}).get("calc") if isinstance(li.raw, dict) else None
    if c and isinstance(c, dict):
        roi = c.get("roi_pct")
        if isinstance(roi, (int, float)):
            return min(100, max(0, int(50 + roi)))
    return 0


async def enrich_top_n(listings: list[Listing], top_n: int = 100, concurrency: int = 4) -> dict:
    """Send top-N listings (by internal grade) to RentCast and merge results.

    Returns a summary dict with counts.
    """
    key = _api_key()
    if not key:
        log.info("rentcast.skip", reason="no_api_key")
        return {"queried": 0, "matched": 0, "skipped": "no API key"}

    # Sort by internal overall_score DESC, take top N (with a sale_date if possible)
    sortable = sorted(
        listings,
        key=lambda li: (_internal_score(li), 0 if li.sale_date is None else 1, li.opening_bid or 0),
        reverse=True,
    )
    targets = sortable[:top_n]

    sem = asyncio.Semaphore(concurrency)
    counts = {"queried": 0, "matched": 0, "comparables_found": 0}

    async with client(timeout=30.0) as c:

        async def one(li: Listing) -> None:
            address = _build_address(li)
            if not address:
                return
            async with sem:
                counts["queried"] += 1
                value = await avm_value(c, address, key)
                # Skip rent-AVM unless residential and small property (saves quota)
                rent = None
                if value:
                    rent = await avm_rent(c, address, key)
                summary = _apply_to_listing(li, value, rent)
                if summary:
                    counts["matched"] += 1
                    counts["comparables_found"] += summary.get("comparables_count", 0) or 0

        await asyncio.gather(*(one(li) for li in targets))

    log.info("rentcast.done", **counts, top_n=top_n)
    return counts


def update_grade_with_rentcast(li: Listing) -> None:
    """If RentCast returned an AVM, blend it into the internal grade.

    Strategy: replace ARV in the calc with weighted average:
      blended_arv = 0.65 * rentcast_avm + 0.35 * internal_arv_expected
    Then recompute downstream metrics (max_bid_70, ROI, profit) and rerun grade.
    """
    if not isinstance(li.raw, dict):
        return
    rc = li.raw.get("rentcast") or {}
    rc_avm = rc.get("avm_price")
    if not rc_avm or rc_avm <= 0:
        return

    # Re-import here to avoid circular import at module load
    from . import calc as _calc, grading as _grading

    # Bias toward RentCast (authoritative source); keep internal as a sanity check
    internal_arv = (li.raw.get("calc") or {}).get("arv_expected") or 0
    if internal_arv:
        blended = round(0.65 * rc_avm + 0.35 * internal_arv, -2)
    else:
        blended = round(rc_avm, -2)

    # Force the calc to use the RentCast value as ARV
    li.market_value = blended  # primary signal for calc._arv_signals

    new_calc = _calc.compute(li)
    new_grade = _grading.grade(li, new_calc)
    li.raw["calc"] = _calc.to_dict(new_calc)
    li.raw["grade"] = _grading.to_dict(new_grade)
    li.raw.setdefault("rentcast", {})["blended_arv"] = blended
    li.raw["rentcast"]["arv_source"] = "rentcast_blended"
