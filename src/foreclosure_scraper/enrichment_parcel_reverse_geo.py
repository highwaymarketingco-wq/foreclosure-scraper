"""Reverse-geocode parcel centroid for listings that have a confident
parcel match but no situs address.

Some county GIS layers (Cleveland NC, Cherokee SC, Mitchell NC, …) carry
parcel polygons + owner names but no situs/property-address field. The
parcel centroid is still useful: a Nominatim reverse lookup gives the
nearest road + house number, which is *approximate* but actionable for
human review.

Policy: the result is written to ``li.raw["parcel_resolution"]
.reverse_geo_approx`` (annotated as approximate) and DOES NOT overwrite
``li.street_address``. Investors will use this data — we never commit a
synthesized address as if it were authoritative.

Rate-limited to Nominatim's TOS (1 request/second). Bounded to listings
with usable data (parcel_id + lat/lng + missing or placeholder street).
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# Synthetic-address markers — listings with these as street_address still
# count as "address-less" for the purpose of this enrichment.
_SYNTHETIC_PREFIXES = (
    "Lis Pendens ",
    "Vacant parcel",
    "Bk Property",
    "Tax Sale",
    "Tax Lien",
    "Bankruptcy ",
    "Property in ",
)


def _is_address_less(li: Listing) -> bool:
    sa = (li.street_address or "").strip()
    if not sa:
        return True
    return any(sa.startswith(p) for p in _SYNTHETIC_PREFIXES)


def _has_useful_centroid(li: Listing) -> bool:
    if not li.parcel_id or not li.latitude or not li.longitude:
        return False
    # Bounding box for NC + SC (rough). Reject (0,0) or wildly out-of-area
    # coords that would produce nonsense reverse-geo results.
    return 32.0 <= li.latitude <= 37.0 and -84.5 <= li.longitude <= -75.0


async def _reverse_geo(c: httpx.AsyncClient, lat: float, lon: float) -> Optional[dict]:
    """Nominatim reverse lookup. Returns {display_name, address} or None."""
    try:
        r = await c.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat, "lon": lon, "format": "json",
                "zoom": 18, "addressdetails": 1,
            },
            headers={"User-Agent": "foreclosure-scraper/parcel-reverse-geo"},
            timeout=20.0,
        )
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


async def enrich_parcel_reverse_geo(listings: list[Listing]) -> dict:
    """For every listing with a confident parcel_id + centroid but no real
    street_address, do a Nominatim reverse-geo lookup and annotate the raw
    blob with the approximate address. Never touches ``li.street_address``.
    """
    targets = [
        li for li in listings
        if _is_address_less(li) and _has_useful_centroid(li)
    ]
    if not targets:
        log.info("parcel_reverse_geo.no_targets")
        return {"queried": 0, "annotated": 0}

    log.info("parcel_reverse_geo.start", target_count=len(targets))
    stats = {"queried": 0, "annotated": 0, "no_match": 0}

    # Nominatim's TOS: max 1 request/second from a single client. We use a
    # token bucket via asyncio.sleep (no concurrency).
    async with httpx.AsyncClient() as c:
        for li in targets:
            # Skip if a previous run already annotated this listing — keep
            # the enrichment idempotent across weekly cycles.
            already = (li.raw or {}).get("parcel_resolution", {}) if isinstance(li.raw, dict) else {}
            if already.get("reverse_geo_approx"):
                continue

            stats["queried"] += 1
            j = await _reverse_geo(c, li.latitude, li.longitude)
            await asyncio.sleep(1.05)  # be polite to Nominatim

            if not j or not j.get("display_name"):
                stats["no_match"] += 1
                continue

            addr = j.get("address") or {}
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw.setdefault("parcel_resolution", {})
            li.raw["parcel_resolution"]["reverse_geo_approx"] = j["display_name"]
            li.raw["parcel_resolution"]["reverse_geo_components"] = {
                "house_number": addr.get("house_number"),
                "road": addr.get("road"),
                "city": addr.get("city") or addr.get("town") or addr.get("village"),
                "county": addr.get("county"),
                "state": addr.get("state"),
                "postcode": addr.get("postcode"),
            }
            li.raw["parcel_resolution"]["reverse_geo_note"] = (
                "Approximate: nearest-road snap from parcel centroid. "
                "Verify before relying on this address."
            )
            stats["annotated"] += 1

    log.info("parcel_reverse_geo.done", **stats)
    return stats
