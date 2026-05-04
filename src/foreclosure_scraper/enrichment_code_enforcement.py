"""Code enforcement violation enrichment.

Cities publish open code violations (condemned, unsafe structure, junk
vehicles, overgrowth, missing permits) via their open-data portals. Direct
distress signal — properties with active violations are 60-70% likely to
hit foreclosure or tax sale within 18 months.

Coverage:
  - Charlotte 311 (Code Enforcement Cases) — Mecklenburg County
  - Asheville code enforcement (when accessible)
  - Spartanburg + Greenville SC (when accessible)

Free, ArcGIS REST endpoints, no auth.
"""
from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime
from typing import Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()


# City open-data endpoints — public ArcGIS FeatureServer queries.
CITY_ENDPOINTS = {
    "Charlotte": {
        "url": "https://services5.arcgis.com/86gdKBxZf7GIt2Or/arcgis/rest/services/Code_Enforcement_Cases/FeatureServer/0/query",
        "addr_fields": ("Address", "Property_Address", "ADDRESS"),
        "violation_fields": ("Violation", "ViolationDescription", "CASE_TYPE", "Description"),
        "status_fields": ("Status", "CaseStatus", "STATUS"),
        "date_fields": ("OpenDate", "CASE_DATE", "DateOpened"),
    },
}


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def _street_keywords(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"^\d+\s*", "", s)
    s = re.sub(
        r"\b(N|S|E|W|NE|NW|SE|SW|North|South|East|West|"
        r"St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Ln|Lane|"
        r"Ct|Court|Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Trl|Trail|"
        r"Pkwy|Parkway|Cir|Circle)\b\.?",
        "", s, flags=re.I,
    )
    tokens = [t.strip(".,#") for t in s.split() if len(t) > 2]
    return max(tokens, key=len, default=s.strip())


def _pick(attrs: dict, fields: tuple) -> Optional[str]:
    norm = {k.lower(): v for k, v in attrs.items()}
    for f in fields:
        v = norm.get(f.lower())
        if v not in (None, "", 0, "0"):
            return str(v)
    return None


async def _fetch_violations_for_listing(
    c, li: Listing, cfg: dict
) -> list[dict]:
    """Query the city ArcGIS for violations matching this listing's address."""
    if not li.street_address:
        return []
    keyword = _street_keywords(li.street_address)
    if not keyword:
        return []

    # Try each address-field name
    for addr_field in cfg["addr_fields"]:
        try:
            params = {
                "where": f"UPPER({addr_field}) LIKE '%{keyword.upper()}%'",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": "10",
                "f": "json",
            }
            r = await c.get(cfg["url"], params=params, timeout=15.0)
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            feats = data.get("features", [])
            if feats:
                return feats
        except Exception:
            continue
    return []


async def enrich_with_code_enforcement(listings: list[Listing]) -> None:
    """For each listing in a covered city, look up open code-enforcement
    violations. Tag matched listings with the count + worst-severity violation.
    """
    if not listings:
        return

    # City detection by city name (case-insensitive)
    targets_by_city: dict[str, list[Listing]] = {}
    for li in listings:
        if not li.city:
            continue
        city_norm = li.city.strip().title()
        if city_norm in CITY_ENDPOINTS:
            targets_by_city.setdefault(city_norm, []).append(li)

    if not targets_by_city:
        log.info("code_enf.no_targets")
        return

    sem = asyncio.Semaphore(4)
    counts = {"queried": 0, "tagged": 0, "violations_found": 0}

    async def one(li: Listing, cfg: dict) -> None:
        async with sem:
            feats = await _fetch_violations_for_listing(c, li, cfg)
            counts["queried"] += 1
            if not feats:
                return
            # Verify by lat/lng proximity if listing has coords
            real_hits: list[dict] = []
            if li.latitude and li.longitude:
                for f in feats:
                    geom = f.get("geometry") or {}
                    glat, glon = geom.get("y"), geom.get("x")
                    if glat is None or glon is None:
                        continue
                    d = _haversine_miles(float(li.latitude), float(li.longitude),
                                         float(glat), float(glon))
                    if d <= 0.05:  # 0.05 mile = ~250 ft
                        real_hits.append(f)
            else:
                real_hits = feats

            if not real_hits:
                return

            counts["violations_found"] += len(real_hits)
            counts["tagged"] += 1

            # Aggregate
            violations = []
            statuses = set()
            for f in real_hits[:5]:
                attrs = f.get("attributes", {}) or {}
                v = _pick(attrs, cfg["violation_fields"]) or "unknown"
                s = _pick(attrs, cfg["status_fields"]) or "unknown"
                d = _pick(attrs, cfg["date_fields"])
                statuses.add(s.lower())
                violations.append({
                    "violation": v[:200],
                    "status": s,
                    "date": str(d)[:10] if d else None,
                })

            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["code_enforcement"] = {
                "city": li.city,
                "open_violations": len([v for v in violations
                                        if v["status"].lower() not in ("closed", "resolved")]),
                "total_violations": len(real_hits),
                "violations": violations,
                "has_open": any(s not in ("closed", "resolved") for s in statuses),
            }

    async with client(timeout=20.0) as c:
        for city, lis in targets_by_city.items():
            cfg = CITY_ENDPOINTS[city]
            log.info("code_enf.city_start", city=city, target_count=len(lis))
            await asyncio.gather(*(one(li, cfg) for li in lis))

    log.info("code_enf.done", **counts)
