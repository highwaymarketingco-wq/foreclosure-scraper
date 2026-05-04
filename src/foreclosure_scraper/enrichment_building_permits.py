"""Building permit enrichment — recent permits = active investment signal,
stale 5+ year-old open permits = abandoned project.

Charlotte publishes building permits at services.arcgis.com via their
open-data portal. We hit the FeatureServer with the listing's street
keyword, verify by lat/lng proximity, and tag with permit count + recent
issue dates.

Free, ArcGIS REST, no auth.

For listings with active recent permits → positive signal (rehab in
progress, ARV uplift potential).
For listings with stale open permits older than 3 years → negative signal
(rehab abandoned, expired permits = code violation).
"""
from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timedelta
from typing import Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()


CITY_PERMIT_ENDPOINTS = {
    # Charlotte building permits — discovered via data.charlottenc.gov search
    "Charlotte": {
        "url": "https://services.arcgis.com/ZTvQ9NuewyLypkyr/arcgis/rest/services/Building_Permits/FeatureServer/0/query",
        "addr_fields": ("Site_Address", "Address", "ADDRESS", "Property_Address"),
        "type_fields": ("Permit_Type", "Type", "Application_Type"),
        "status_fields": ("Status", "Permit_Status", "STATUS"),
        "date_fields": ("Issue_Date", "Application_Date", "DateIssued"),
        "value_fields": ("Estimated_Value", "Total_Value", "Project_Value"),
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


def _street_keyword(s: str) -> str:
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


async def _fetch_permits(c, li: Listing, cfg: dict) -> list[dict]:
    if not li.street_address:
        return []
    keyword = _street_keyword(li.street_address)
    if not keyword:
        return []
    for addr_field in cfg["addr_fields"]:
        try:
            params = {
                "where": f"UPPER({addr_field}) LIKE '%{keyword.upper()}%'",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": "20",
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


async def enrich_with_building_permits(listings: list[Listing]) -> None:
    if not listings:
        return
    targets_by_city: dict[str, list[Listing]] = {}
    for li in listings:
        if not li.city:
            continue
        if li.city.strip().title() in CITY_PERMIT_ENDPOINTS:
            targets_by_city.setdefault(li.city.strip().title(), []).append(li)
    if not targets_by_city:
        log.info("permits.no_targets")
        return

    sem = asyncio.Semaphore(4)
    counts = {"queried": 0, "tagged": 0}
    cutoff_recent = datetime.utcnow() - timedelta(days=730)
    cutoff_stale = datetime.utcnow() - timedelta(days=1095)

    async def one(li: Listing, cfg: dict) -> None:
        async with sem:
            feats = await _fetch_permits(c, li, cfg)
            counts["queried"] += 1
            if not feats:
                return
            real_hits: list[dict] = []
            if li.latitude and li.longitude:
                for f in feats:
                    geom = f.get("geometry") or {}
                    glat, glon = geom.get("y"), geom.get("x")
                    if glat is None or glon is None:
                        continue
                    if _haversine_miles(float(li.latitude), float(li.longitude),
                                        float(glat), float(glon)) <= 0.05:
                        real_hits.append(f)
            else:
                real_hits = feats
            if not real_hits:
                return

            recent = 0
            stale_open = 0
            permits_summary: list[dict] = []
            for f in real_hits[:5]:
                attrs = f.get("attributes") or {}
                t = _pick(attrs, cfg["type_fields"]) or "?"
                s = _pick(attrs, cfg["status_fields"]) or "?"
                d_str = _pick(attrs, cfg["date_fields"])
                v = _pick(attrs, cfg["value_fields"]) or ""
                d_parsed = None
                if d_str:
                    try:
                        # ArcGIS often returns epoch ms
                        d_parsed = (
                            datetime.fromtimestamp(int(d_str) / 1000)
                            if d_str.isdigit() and len(d_str) >= 10
                            else None
                        )
                    except Exception:
                        d_parsed = None
                if d_parsed:
                    if d_parsed > cutoff_recent:
                        recent += 1
                    elif d_parsed < cutoff_stale and "open" in s.lower():
                        stale_open += 1
                permits_summary.append({
                    "type": t[:80],
                    "status": s[:40],
                    "date": d_parsed.isoformat() if d_parsed else None,
                    "value": v,
                })

            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["building_permits"] = {
                "city": li.city,
                "total": len(real_hits),
                "recent_permits_2y": recent,
                "stale_open_permits_3y_plus": stale_open,
                "permits": permits_summary,
            }
            counts["tagged"] += 1

    async with client(timeout=20.0) as c:
        for city, lis in targets_by_city.items():
            cfg = CITY_PERMIT_ENDPOINTS[city]
            log.info("permits.city_start", city=city, target_count=len(lis))
            await asyncio.gather(*(one(li, cfg) for li in lis))

    log.info("permits.done", **counts)
