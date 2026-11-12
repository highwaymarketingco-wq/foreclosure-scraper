"""FEMA repetitive flood loss enrichment.

OpenFEMA publishes the National Flood Insurance Program (NFIP) Multiple Loss
Properties dataset — structures that have had multiple flood claims in
program history. "Repetitive loss" properties are a stronger distress
signal than a basic flood-zone tag (which we already have via NFHL).

Free, no auth, FEMA OpenFEMA API.

We pre-load NC + SC repetitive loss properties (small dataset, can fit in
memory) and then match each foreclosure listing by (zip, lat/lng proximity).
For matched listings, tag raw.fema_repetitive_loss with claim history.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

API_BASE = "https://www.fema.gov/api/open/v1/NfipMultipleLossProperties"
TARGET_STATES = ("NC", "SC")


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8  # earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


async def _fetch_state_loss_properties(c, state: str) -> list[dict]:
    """Page through OpenFEMA for one state. Each page = up to 1000 records."""
    out: list[dict] = []
    skip = 0
    page_size = 1000
    while True:
        params = {
            "$filter": f"stateAbbreviation eq '{state}'",
            "$top": page_size,
            "$skip": skip,
        }
        try:
            r = await c.get(API_BASE, params=params, timeout=30.0)
            if r.status_code != 200:
                break
            data = r.json()
            items = data.get("NfipMultipleLossProperties", [])
            out.extend(items)
            if len(items) < page_size:
                break
            skip += page_size
            if skip >= 5000:  # safety cap
                break
        except Exception as exc:
            log.warning("fema.fetch_fail", state=state, error=str(exc)[:200])
            break
    return out


async def enrich_with_fema_repetitive_loss(listings: list[Listing]) -> None:
    """Tag listings located near a FEMA repetitive-loss property with the
    nearest match. Match by zip + 0.25 mile radius via lat/lng.
    """
    if not listings:
        return

    targets = [li for li in listings if li.zip_code or (li.latitude and li.longitude)]
    if not targets:
        log.info("fema.no_targets")
        return

    log.info("fema.start", target_count=len(targets))

    async with client(timeout=30.0) as c:
        all_loss: list[dict] = []
        for state in TARGET_STATES:
            items = await _fetch_state_loss_properties(c, state)
            all_loss.extend(items)
            log.info("fema.state_loaded", state=state, count=len(items))

    if not all_loss:
        log.info("fema.no_loss_records")
        return

    # Index by zip for fast lookup
    by_zip: dict[str, list[dict]] = {}
    for item in all_loss:
        z = str(item.get("zipCode") or "")[:5]
        if z:
            by_zip.setdefault(z, []).append(item)

    # Match each listing
    matched = 0
    for li in targets:
        z = (li.zip_code or "")[:5]
        candidates = by_zip.get(z, [])
        if not candidates and li.latitude and li.longitude:
            # Fall back to scanning all (slow but bounded)
            candidates = all_loss
        if not candidates:
            continue

        best: Optional[dict] = None
        best_dist = 999.0
        if li.latitude and li.longitude:
            for item in candidates:
                ilat, ilon = item.get("latitude"), item.get("longitude")
                if ilat is None or ilon is None:
                    continue
                d = _haversine_miles(float(li.latitude), float(li.longitude),
                                     float(ilat), float(ilon))
                if d < best_dist:
                    best_dist = d
                    best = item
        elif candidates:
            # No coords on the listing — best we can do is "in same zip"
            best = candidates[0]
            best_dist = -1.0  # unknown distance

        if best and (best_dist <= 0.25 or best_dist < 0):
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["fema_repetitive_loss"] = {
                "matched_at_distance_mi": round(best_dist, 3) if best_dist >= 0 else None,
                "match_method": "lat_lng" if best_dist >= 0 else "zip_only",
                "nfip_repetitive_loss": bool(best.get("nfipRl")),
                "nfip_severe_repetitive_loss": bool(best.get("nfipSrl")),
                "fma_repetitive_loss": bool(best.get("fmaRl")),
                "flood_zone": best.get("floodZone"),
                "occupancy_type": best.get("occupancyType"),
                "original_construction_year": (
                    str(best.get("originalConstructionDate") or "")[:4] or None
                ),
                "as_of_date": str(best.get("asOfDate") or "")[:10],
                "community_id": best.get("communityIdNumber"),
                "community_name": best.get("communityName"),
            }
            matched += 1

    log.info("fema.done", targets=len(targets), matched=matched,
             total_loss_records=len(all_loss))
