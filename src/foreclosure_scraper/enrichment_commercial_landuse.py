"""Commercial land-use reclassifier — recover commercial property miscast as land.

`property_kind` is set by whichever scraper found the lead, from whatever that
source guessed, and is never reconciled against the county's own land-use code.
The result on the published board: 206 leads carry a plainly commercial
`land_use` and 189 of them are typed as something else — 84 "Eating & Drinking
Estab" filed as `land`, gasoline service stations filed as `land`, retail filed
as `single_family`.

That is not cosmetic. A former gas station at $159,200 as-is sitting in the land
bucket is an environmental-liability property being valued and routed as a
vacant lot. Fuel-storage sites carry contamination exposure that changes the
deal entirely, so they are tagged separately here rather than folded in.

MEASURED FALSE-POSITIVE PROBLEM (2026-09-09). Spartanburg's land_use encodes a
HISTORICAL or ZONING use, not current physical use. Of 190 leads a naive
land_use match would flip, 185 carry residential structure signals:
"Groceries-Retail" with 4 bedrooms / 1,130 sqft, "Drinking Places" with 8
bedrooms, "Gasoline Service Station" with 3 bedrooms. Those are houses. A ~97%
false-positive rate, and tagging a 3-bedroom house as a contaminated fuel site is
worse than leaving it alone.

So this NEVER changes property_kind on structure evidence alone. It requires
land_use to say commercial AND the parcel to show no residential structure
(no bedroom count, and either no living_sqft or a footprint too large to be a
house). Everything else gets an advisory raw.land_use_commercial_hint only -
visible for review, authoritative for nothing.

Pure-local: reads `land_use`, already present from the GIS/parcel enrichers. No
network.
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from .models import Listing, PropertyKind

log = structlog.get_logger()

# County land-use strings that mean "this is a commercial building/site".
_COMMERCIAL_RE = re.compile(
    r"\b(commercial|warehouse|industrial|retail|office|shopping|store|"
    r"eating|drinking|restaurant|motel|hotel|tavern|bar|garage|"
    r"service station|gasoline|filling station|manufactur|"
    r"wholesale|distribution|mini.?storage|self.?storage)\b",
    re.I,
)

# Sites with fuel/solvent storage history. Contamination exposure is a distinct
# risk class, not a property type, so it is stamped alongside rather than
# replacing the kind.
_ENVIRONMENTAL_RE = re.compile(
    r"\b(gasoline|service station|filling station|dry.?clean|"
    r"auto.?repair|body.?shop|salvage|junk.?yard|landfill)\b",
    re.I,
)

# Land-use text that mentions a commercial word but is NOT a commercial parcel.
_NEGATIVE_RE = re.compile(
    r"\b(commercial forest|forest production|agricultur|timber)\b", re.I
)


def enrich_commercial_landuse(listings: Iterable[Listing]) -> dict:
    stats = {"scanned": 0, "reclassified": 0, "environmental": 0, "already": 0, "hint_only": 0}
    for li in listings:
        lu = getattr(li, "land_use", None)
        if not isinstance(lu, str) or not lu.strip():
            continue
        stats["scanned"] += 1
        if _NEGATIVE_RE.search(lu):
            continue
        if not _COMMERCIAL_RE.search(lu):
            continue

        # RESIDENTIAL-STRUCTURE GUARD. A bedroom count, or a house-sized
        # footprint, means the county code is stale/zoning-derived and must not
        # override what is physically there.
        beds = getattr(li, "bedrooms", None)
        sqft = getattr(li, "living_sqft", None)
        looks_residential = bool(beds) or (
            isinstance(sqft, (int, float)) and 0 < sqft < 5000)

        kind = getattr(li, "property_kind", None)
        kind_s = getattr(kind, "value", kind)

        if looks_residential:
            # Advisory only. Never rewrites the kind, never asserts contamination.
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["land_use_commercial_hint"] = {
                "land_use": lu.strip()[:60],
                "note": "county land_use reads commercial but the parcel has "
                        "residential structure - likely historical or zoning code",
                "source": "county_land_use",
            }
            stats["hint_only"] = stats.get("hint_only", 0) + 1
            continue

        if str(kind_s or "").lower() == "commercial":
            stats["already"] += 1
        else:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["property_kind_reclassified"] = {
                "from": str(kind_s or "unknown"),
                "to": "commercial",
                "land_use": lu.strip()[:60],
                "source": "county_land_use",
            }
            try:
                li.property_kind = PropertyKind.COMMERCIAL
            except Exception:  # noqa: BLE001 — enum shape varies; fall back to the string
                li.property_kind = "commercial"
            stats["reclassified"] += 1

        if _ENVIRONMENTAL_RE.search(lu):
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["environmental_risk"] = {
                "kind": "fuel_or_solvent_site",
                "land_use": lu.strip()[:60],
                "note": "contamination exposure — verify before acquisition",
                "source": "county_land_use",
            }
            stats["environmental"] += 1

    log.info("commercial_landuse.done", **stats)
    return stats
