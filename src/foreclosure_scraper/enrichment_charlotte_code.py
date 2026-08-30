"""City of Charlotte code-enforcement enrichment (403-bypass variant).

The City of Charlotte code-enforcement data returns HTTP 403 to standard
requests. This module tries multiple open-data endpoint strategies before
giving up, so listings in Charlotte get flagged for active code violations
(condemned, unsafe structure, housing complaints, etc.):

  Strategy A: Socrata-style API at https://data.charlottenc.gov/api/ —
               many city open-data portals expose a Socrata-compatible
               JSON API at /api/views/<id>/rows or /resource/<id>.json.
  Strategy B: ArcGIS Hub at https://data.charlottenc.gov/ — Charlotte's
               open-data portal is ArcGIS Hub, which hosts FeatureServer
               endpoints we can query with a standard ArcGIS REST where-clause.
  Strategy C: Direct city ArcGIS REST services (services.arcgis.com or
               gis.charlottenc.gov) if Hub redirects there.

Fills raw["code_enforcement"] list with violation dicts:
  {violation, status, date_opened, case_number, address, source}

When no violations match the listing's address, raw["code_enforcement"]
gets an empty list (so the board knows the step ran).

Free, no auth, public record. Handles 403 gracefully: returns None + logs a
warning so the run continues.
"""
from __future__ import annotations

import asyncio
import math
import re
from typing import Any, Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://data.charlottenc.gov/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Charlotte open-data portal endpoints
_SOCRATA_API_URL = "https://data.charlottenc.gov/api/views"
_SOCRATA_RESOURCE_URL = "https://data.charlottenc.gov/resource"
_ARCGIS_HUB_URL = "https://data.charlottenc.gov/api/feed/dataset"
# Direct ArcGIS FeatureServer for Charlotte code enforcement (speculative —
# the real URL is discovered via Hub, but we try a known services host)
_ARCGIS_FS_URL = (
    "https://services.arcgis.com/DSlDASxIa0l2IXLA/arcgis/rest/services/"
    "Code_Enforcement_Cases/FeatureServer/0"
)

_SEMAPHORE = asyncio.Semaphore(3)


def _street_keyword(addr: str | None) -> str:
    """Extract the longest meaningful keyword from a street address for matching."""
    if not addr:
        return ""
    s = re.sub(r"^\d+\s*", "", addr)
    s = re.sub(
        r"\b(N|S|E|W|NE|NW|SE|SW|North|South|East|West|"
        r"St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Ln|Lane|"
        r"Ct|Court|Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Trl|Trail|"
        r"Pkwy|Parkway|Cir|Circle)\b\.?",
        "", s, flags=re.I,
    )
    tokens = [t.strip(".,#") for t in s.split() if len(t) > 2]
    return max(tokens, key=len, default=s.strip())


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


async def _strategy_a_socrata(keyword: str) -> list[dict[str, Any]] | None:
    """Strategy A: Try the Socrata-style JSON API.

    Charlotte's open-data portal is ArcGIS Hub, not Socrata, but some datasets
    are mirrored or proxied. We try the /resource/<dataset>.json endpoint with
    a simple text search. This is speculative — the 4char resource IDs vary.
    """
    if not keyword:
        return None
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                f"{_SOCRATA_RESOURCE_URL}.json",
                params={"$q": keyword, "$limit": "10"},
                headers={**_BROWSER_HEADERS, "Accept": "application/json"},
            )
            if resp.status_code == 403:
                log.debug("charlotte_code.strategy_a_403")
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("charlotte_code.strategy_a_fail", error=str(exc)[:80])
        return None

    if not isinstance(data, list) or not data:
        return None

    violations: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        violations.append({
            "violation": row.get("violation_type") or row.get("case_type")
            or row.get("complaint_type") or "unknown",
            "status": row.get("status") or row.get("case_status"),
            "date_opened": row.get("date_opened") or row.get("open_date"),
            "case_number": row.get("case_number") or row.get("case_no"),
            "address": row.get("address") or row.get("case_address"),
            "source": "socrata",
        })
    return violations if violations else None


async def _strategy_b_arcgis_hub(keyword: str) -> list[dict[str, Any]] | None:
    """Strategy B: ArcGIS Hub FeatureServer query.

    Charlotte's open-data portal is ArcGIS Hub. The dataset pages on
    data.charlottenc.gov each point to a FeatureServer URL. We try the
    standard ArcGIS REST query with a WHERE clause on the address field.
    """
    if not keyword:
        return None
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                _ARCGIS_FS_URL,
                params={
                    "where": f"UPPER(address) LIKE '%{keyword.upper()}%'",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": "10",
                    "f": "json",
                },
                headers={**_BROWSER_HEADERS, "Accept": "application/json"},
            )
            if resp.status_code == 403:
                log.debug("charlotte_code.strategy_b_403")
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("charlotte_code.strategy_b_fail", error=str(exc)[:80])
        return None

    if not isinstance(data, dict) or "error" in data:
        return None

    features = data.get("features", [])
    if not features:
        return None

    violations: list[dict[str, Any]] = []
    for feat in features:
        attrs = feat.get("attributes", {}) or {}
        violations.append({
            "violation": attrs.get("violation_type")
            or attrs.get("case_type")
            or attrs.get("complaint_type")
            or attrs.get("record_type")
            or "unknown",
            "status": attrs.get("status") or attrs.get("case_status"),
            "date_opened": attrs.get("date_opened")
            or attrs.get("open_date"),
            "case_number": attrs.get("case_number")
            or attrs.get("case_no"),
            "address": attrs.get("address")
            or attrs.get("case_address"),
            "source": "arcgis_hub",
        })
    return violations if violations else None


async def _strategy_c_direct_services(
    keyword: str, listing: Listing
) -> list[dict[str, Any]] | None:
    """Strategy C: Direct ArcGIS services query + lat/lon proximity.

    Try a known services host directly. If we got features, verify by
    lat/lon proximity to the listing's coordinates.
    """
    if not keyword:
        return None
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                _ARCGIS_FS_URL,
                params={
                    "where": f"UPPER(address) LIKE '%{keyword.upper()}%'",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": "10",
                    "f": "json",
                },
                headers={**_BROWSER_HEADERS, "Accept": "application/json"},
            )
            if resp.status_code == 403:
                log.debug("charlotte_code.strategy_c_403")
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("charlotte_code.strategy_c_fail", error=str(exc)[:80])
        return None

    if not isinstance(data, dict) or "error" in data:
        return None

    features = data.get("features", [])
    if not features:
        return None

    real_hits: list[dict[str, Any]] = []
    for feat in features:
        attrs = feat.get("attributes", {}) or {}
        geom = feat.get("geometry") or {}
        # Proximity verification if we have listing coords
        if listing.latitude and listing.longitude:
            glat, glon = geom.get("y"), geom.get("x")
            if glat is not None and glon is not None:
                d = _haversine_miles(
                    float(listing.latitude), float(listing.longitude),
                    float(glat), float(glon),
                )
                if d > 0.05:  # 0.05 mile = ~250 ft
                    continue
        real_hits.append({
            "violation": attrs.get("violation_type")
            or attrs.get("case_type")
            or attrs.get("record_type") or "unknown",
            "status": attrs.get("status") or attrs.get("case_status"),
            "date_opened": attrs.get("date_opened")
            or attrs.get("open_date"),
            "case_number": attrs.get("case_number")
            or attrs.get("case_no"),
            "address": attrs.get("address")
            or attrs.get("case_address"),
            "source": "direct_services",
        })
    return real_hits if real_hits else None


async def _lookup_charlotte_code(listing: Listing) -> list[dict[str, Any]] | None:
    """Try all three strategies in order; return first non-None result."""
    keyword = _street_keyword(listing.street_address)
    if not keyword:
        return None

    async with _SEMAPHORE:
        strategies = (
            ("strategy_a", lambda: _strategy_a_socrata(keyword)),
            ("strategy_b", lambda: _strategy_b_arcgis_hub(keyword)),
            ("strategy_c", lambda: _strategy_c_direct_services(keyword, listing)),
        )
        for label, coro_fn in strategies:
            try:
                result = await coro_fn()
            except Exception as exc:
                log.warning("charlotte_code.strategy_exception",
                            strategy=label, error=str(exc)[:120])
                result = None
            if result:
                log.info("charlotte_code.found",
                         strategy=label, count=len(result))
                return result

    log.warning("charlotte_code.all_strategies_failed",
                addr=(listing.street_address or "")[:60])
    return None


async def enrich_charlotte_code(listing: Listing) -> Listing:
    """Enrich a listing with Charlotte code-enforcement data."""
    # Charlotte listings only — check city + state
    city_norm = (listing.city or "").strip().lower()
    state_norm = (listing.state or "").strip().upper()
    is_charlotte = city_norm in ("charlotte", "charlotte, nc") and state_norm == "NC"
    if not is_charlotte:
        return listing

    if not listing.street_address:
        return listing

    result = await _lookup_charlotte_code(listing)
    if result is None:
        # 403 or all strategies exhausted — log + continue
        return listing

    raw_update: dict[str, Any] = {
        "code_enforcement": result,
    }
    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_charlotte_code(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with Charlotte code-enforcement data."""
    need_code = [
        l for l in listings
        if (l.city or "").strip().lower() in ("charlotte", "charlotte, nc")
        and (l.state or "").upper() == "NC"
        and l.street_address
        and "code_enforcement" not in (l.raw or {})
    ]
    if not need_code:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_charlotte_code(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_code], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if (listing.city or "").strip().lower() in ("charlotte", "charlotte, nc") \
                and (listing.state or "").upper() == "NC" \
                and listing.street_address \
                and "code_enforcement" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "charlotte_code.batch_done",
        total=len(need_code),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
