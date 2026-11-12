"""Land-value share of total appraised value (Dirty Deeds Tier A #11).

docs/dirty_deeds_synthesis_2026-09-10.md: "Land value / total assessed ratio
... Switches the valuation method and the mow/trim decision. Acreage ringed
by townhouses is a redevelopment parcel, not a house." The synthesis pairs
the ratio with denser surrounding use; this module only computes the ratio.
The surroundings half needs parcel geometry the board does not store.

COVERAGE IS SMALL AND SAID SO. Measured 2026-09-18 on the live board, the
only blocks that carry a land vs improvement split are:
  - gis_attrs_full: CurrentAppraisedLandValue / CurrentAppraisedBuildingValue
    (~1.8K rows with a land value, ~1.3K with a building value)
  - gaston_gis:     FMV_LAND / FMV_IMPRV / VacantImpro (~6.3K land values)
Everything else (cama, lrcpwa, lexington_assessment, assessor_card) holds one
total, not a split. So this signal can reach roughly 5% of the board, not
more, until another source exposes a split.

100% offline. Never overwrites, never drops a lead; writes raw['land_ratio'].
"""
from __future__ import annotations

from typing import Iterable, Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# Land worth at least this share of the total, with a real structure on it,
# means the value is in the dirt: teardown / redevelopment candidate.
LAND_HEAVY_SHARE = 0.60
_VACANT_CODES = {"V", "VAC", "VACANT"}


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _from_gis_attrs_full(raw: dict) -> Optional[tuple[float, Optional[float], str]]:
    a = raw.get("gis_attrs_full")
    if not isinstance(a, dict):
        return None
    land = _num(a.get("CurrentAppraisedLandValue"))
    if land is None or land <= 0:
        return None
    return land, _num(a.get("CurrentAppraisedBuildingValue")), "gis_attrs_full"


def _from_gaston_gis(raw: dict) -> Optional[tuple[float, Optional[float], str]]:
    a = raw.get("gaston_gis")
    if not isinstance(a, dict):
        return None
    land = _num(a.get("FMV_LAND"))
    if land is None or land <= 0:
        return None
    imp = _num(a.get("FMV_IMPRV"))
    if imp is None and str(a.get("VacantImpro") or "").strip().upper() in _VACANT_CODES:
        imp = 0.0  # county says vacant: no structure value is a real zero, not missing
    return land, imp, "gaston_gis"


def compute_land_ratio(li: Listing) -> Optional[dict]:
    raw = li.raw if isinstance(li.raw, dict) else {}
    got = _from_gis_attrs_full(raw) or _from_gaston_gis(raw)
    if got is None:
        return None
    land, imp, source = got
    if imp is None:
        return None  # a ratio needs both halves; never guess the missing one
    total = land + imp
    if total <= 0:
        return None
    share = land / total
    return {
        "land_value": round(land, 2),
        "improvement_value": round(imp, 2),
        "total_value": round(total, 2),
        "land_share": round(share, 3),
        "vacant_land": imp == 0,
        "land_heavy": imp > 0 and share >= LAND_HEAVY_SHARE,
        "source": source,
    }


def enrich_land_ratio(listings: Iterable[Listing]) -> dict:
    stats = {"tagged": 0, "vacant_land": 0, "land_heavy": 0}
    for li in listings:
        block = compute_land_ratio(li)
        if block is None:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["land_ratio"] = block
        stats["tagged"] += 1
        stats["vacant_land"] += bool(block["vacant_land"])
        stats["land_heavy"] += bool(block["land_heavy"])
    if stats["tagged"]:
        log.info("land_ratio.done", **stats)
    return stats
