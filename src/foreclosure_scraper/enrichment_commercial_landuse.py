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

Pure-local: reads `land_use`, already present from the GIS/parcel enrichers. No
network. Fills only — an existing `commercial` kind is never rewritten, and the
original value is preserved on the stamp so the change is auditable.
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
    stats = {"scanned": 0, "reclassified": 0, "environmental": 0, "already": 0}
    for li in listings:
        lu = getattr(li, "land_use", None)
        if not isinstance(lu, str) or not lu.strip():
            continue
        stats["scanned"] += 1
        if _NEGATIVE_RE.search(lu):
            continue
        if not _COMMERCIAL_RE.search(lu):
            continue

        kind = getattr(li, "property_kind", None)
        kind_s = getattr(kind, "value", kind)
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
