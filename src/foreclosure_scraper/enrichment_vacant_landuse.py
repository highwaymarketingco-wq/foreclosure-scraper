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


def _has_cache(memo: dict, county: str, state: str | None) -> bool:
    """A parcel-cache file exists for the county. cached_counties() lists only the dedicated
    PARCEL_LAYERS counties; the other ~60 NC counties are cached off the statewide OneMap layer
    (nc_onemap_cfg) and were skipped here, so their rows never got a land use (Wake's cache holds
    1.74M parcels, all with a land-use value, and 0 board rows used it). State-aware for the
    dual-state names."""
    key = (county, (state or "").upper())
    if key not in memo:
        try:
            memo[key] = parcel_cache._db_path(county, state).exists()  # noqa: SLF001
        except Exception:  # noqa: BLE001 - a dual-state name with no state: nothing cached
            memo[key] = False
    return memo[key]


def enrich_vacant_landuse(listings: Iterable[Listing]) -> dict:
    memo: dict = {}
    stats = {"eligible": 0, "stamped": 0, "land_use_filled": 0}
    for li in listings:
        pid = (li.parcel_id or "").strip()
        county = (li.county or "").strip()
        if not pid or not county:
            continue
        if (li.state or "").upper() == "NC":
            county = parcel_cache._nc_name_ci(county.replace(" County", "").strip()) or county  # noqa: SLF001
        if not _has_cache(memo, county, li.state):
            continue
        rec = parcel_cache.lookup(county, pid, li.state)
        lu = (rec or {}).get("land_use")
        if not lu:
            continue
        stats["eligible"] += 1
        # The county's own class string is the row's land use. It was only ever stamped inside
        # raw.vacant_lot, so a row that is NOT a vacant lot carried no land use at all and the
        # cube counted vacant_lot as unchecked on it (top-80 2026-10-09: Mecklenburg 5 of 17,733
        # rows, Spartanburg 6,995 of 19,380). The comps pass runs earlier in the same run, so this
        # does not change this run's valuation; Listing.land_use is documented as GIS-backfilled.
        if not (getattr(li, "land_use", None) or "").strip():
            clean = str(lu).strip()
            if clean and not clean.isdigit():
                li.land_use = clean.title() if clean.isupper() else clean
                stats["land_use_filled"] = stats.get("land_use_filled", 0) + 1
        if not _VACANT_RE.search(str(lu)):
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        # idempotent — don't re-stamp on a re-run
        if not li.raw.get("vacant_lot"):
            li.raw["vacant_lot"] = {"land_use": str(lu).strip()[:60], "source": "parcel_cache_landuse"}
            stats["stamped"] += 1
    if stats["stamped"] or stats["land_use_filled"]:
        log.info("vacant_landuse.done", **stats)
    return stats
