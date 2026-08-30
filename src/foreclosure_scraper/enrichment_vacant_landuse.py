"""Vacant-land-use proxy — a FREE substitute for the paywalled USPS 90-day vacancy feed.

The county parcel layers we already bulk-download into the parcel cache carry a
land-class / land-use field (Rutherford `Land_Class`, Burke/Henderson `LAND_CLASS`,
Spartanburg `LandUse`). Where that field says the parcel is a VACANT / UNDEVELOPED lot,
we stamp a `vacant_lot` distress facet. This is an undeveloped-land signal (feeds the
LAND_WHOLESALE lane + stacks with absentee/tax), distinct from `vacant` (an unoccupied
HOUSE). Pure-local: reads the cache, no network. No-op for un-cached counties.
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from .models import Listing
from . import parcel_cache

log = structlog.get_logger(__name__)

# land-class text that means "undeveloped / vacant lot" across the county schemas.
_VACANT_RE = re.compile(r"\b(VACANT|UNDEVELOPED)\b", re.I)


def enrich_vacant_landuse(listings: Iterable[Listing]) -> dict:
    cached = parcel_cache.cached_counties()
    stats = {"eligible": 0, "stamped": 0}
    for li in listings:
        pid = (li.parcel_id or "").strip()
        county = (li.county or "").strip()
        if not pid or county not in cached:
            continue
        rec = parcel_cache.lookup(county, pid)
        lu = (rec or {}).get("land_use")
        if not lu:
            continue
        stats["eligible"] += 1
        if not _VACANT_RE.search(str(lu)):
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        # idempotent — don't re-stamp on a re-run
        if not li.raw.get("vacant_lot"):
            li.raw["vacant_lot"] = {"land_use": str(lu).strip()[:60], "source": "parcel_cache_landuse"}
            stats["stamped"] += 1
    if stats["stamped"]:
        log.info("vacant_landuse.done", **stats)
    return stats
