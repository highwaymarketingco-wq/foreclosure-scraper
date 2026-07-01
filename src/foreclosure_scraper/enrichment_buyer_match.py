"""Buyer-match tagger — surface the real buyers who want property in a lead's
county, so a card can show "who to flip this to" (LOCAL, no network).

Research finding (2026-07): no buyer publishes a structured, scrapeable buy box
(county/zip + acreage + price) for rural WNC/Upstate-SC — the "we buy land"
companies name our counties as SEO text funneling to a contact form, builders
take land by relationship/inbound form, and only Brevitas publishes structured
COMMERCIAL wants (state-level). So this is a hand-curated OUTREACH registry, not
a scraped feed: a static county->buyers map built from the buyers that actually
name our footprint. On a qualifying card we attach raw['buyer_match'] =
{land:[...], builders:[...], houses:[...]} with each buyer's name + contact URL +
why, so the operator knows who to call to assign the deal.

Gate BUYER_MATCH=0. Registry is a few dozen static rows — update as buyers change.
"""
from __future__ import annotations

import os
from typing import Iterable

from .models import Listing

_ENABLED = os.environ.get("BUYER_MATCH") != "0"

# Metro grouping for builder demand (builders acquire by submarket).
_ASHEVILLE_METRO = {"Buncombe", "Henderson", "Transylvania", "Madison"}
_GVL_SPART_METRO = {"Greenville", "Spartanburg", "Anderson", "Pickens", "Oconee", "Laurens", "Cherokee"}
_UPSTATE_SC = {"Greenville", "Spartanburg", "Anderson", "Pickens", "Oconee", "Laurens", "Union", "Cherokee"}

# --- Land buyers that name ~all 19 WNC+Upstate-SC counties (blanket coverage) ---
_LAND_BLANKET = [
    {"name": "Bubba Land Company", "url": "https://bubba-land.com/",
     "note": "rural acreage 3+ ac, timberland/farmland outside city limits", "min_acres": 3.0},
    {"name": "Value Land Buyers", "url": "https://www.valuelandbuyers.com/",
     "note": "raw land + vacant lots, any size"},
    {"name": "Selling Land Fast", "url": "https://www.sellinglandfast.com/",
     "note": "rural acreage, raw land, lots, farms"},
]
# --- Upstate-SC regional land/house buyers (county-scoped) ---
_UPSTATE_REGIONAL = [
    {"name": "Greenville Home Solutions", "url": "https://www.greenvillehomesolutions.com/",
     "counties": {"Greenville", "Anderson", "Pickens", "Oconee", "Spartanburg", "Laurens"}, "buys": "land+houses"},
    {"name": "Table Rock Homebuyers", "url": "https://www.tablerockhomebuyers.com/",
     "counties": {"Greenville", "Spartanburg", "Pickens", "Oconee", "Anderson"}, "buys": "land+houses"},
    {"name": "New South Home Buyers", "url": "https://www.newsouthhomebuyers.com/",
     "counties": {"Greenville", "Spartanburg", "Anderson", "Pickens", "Oconee"}, "buys": "land+houses"},
]
# --- Builders with land-acquisition intake, by metro ---
_BUILDERS = [
    {"name": "D.R. Horton (land submittal)", "url": "https://www.drhorton.com/contact-us---property-submittals",
     "metros": _ASHEVILLE_METRO | _GVL_SPART_METRO},
    {"name": "Windsor Built Homes", "url": "https://windsorbuilt.com/land-acquisition/", "metros": _ASHEVILLE_METRO | _UPSTATE_SC},
    {"name": "Meritage Homes SC", "url": "https://www.meritagehomes.com/", "metros": _GVL_SPART_METRO},
    {"name": "Eastwood Homes (Build-On-Your-Lot)", "url": "https://www.eastwoodhomes.com/build-on-your-lot-greenville", "metros": _GVL_SPART_METRO},
    {"name": "Century Complete", "url": "https://www.centurycommunities.com/", "metros": _GVL_SPART_METRO},
]
# --- Blanket cash house-buyers (residential, whole footprint) ---
_HOUSE_BLANKET = [
    {"name": "HomeVestors / We Buy Ugly Houses", "url": "https://www.webuyuglyhouses.com/", "note": "cash for houses, blanket coverage"},
]

_LAND_KINDS = {"land", "vacant_land", "vacant", "lot", "acreage"}


def _norm_county(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().title()


def _is_land(li: Listing) -> bool:
    pk = (li.property_kind.value if hasattr(li.property_kind, "value") else str(li.property_kind or "")).lower()
    if any(k in pk for k in _LAND_KINDS):
        return True
    d = (li.description or "").lower()
    return "vacant lot" in d or "vacant land" in d or "vacant parcel" in d


def _acres(li: Listing):
    raw = li.raw if isinstance(li.raw, dict) else {}
    for src in (raw.get("lrcpwa"), raw.get("gis"), raw):
        if isinstance(src, dict):
            for k in ("acreage", "acres", "calculatedAcres", "deededAcres"):
                v = src.get(k)
                try:
                    if v is not None:
                        return float(str(v).replace(",", ""))
                except (TypeError, ValueError):
                    pass
    return None


def enrich_buyer_match(listings: Iterable[Listing]) -> dict:
    stats = {"matched": 0, "land": 0, "houses": 0}
    if not _ENABLED:
        return stats
    for li in listings:
        county = _norm_county(li)
        if not county:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        is_land = _is_land(li)
        acres = _acres(li)
        land, builders, houses = [], [], []

        if is_land:
            for b in _LAND_BLANKET:
                # honour the one real criterion we found (Bubba = 3+ rural acres)
                if b.get("min_acres") and acres is not None and acres < b["min_acres"]:
                    continue
                land.append({"name": b["name"], "url": b["url"], "why": b["note"]})
            for b in _UPSTATE_REGIONAL:
                if county in b["counties"]:
                    land.append({"name": b["name"], "url": b["url"], "why": f"buys land in {county}"})
            for b in _BUILDERS:
                if county in b["metros"]:
                    builders.append({"name": b["name"], "url": b["url"], "why": f"builder acquiring land in the {county} submarket"})
        else:
            # residential — cash house-buyers (only worth surfacing on distressed leads)
            ds = (raw.get("distress_stack") or {}).get("tier")
            if ds in ("HOT", "WARM"):
                for b in _HOUSE_BLANKET:
                    houses.append({"name": b["name"], "url": b["url"], "why": b["note"]})
                for b in _UPSTATE_REGIONAL:
                    if county in b["counties"]:
                        houses.append({"name": b["name"], "url": b["url"], "why": f"buys houses in {county}"})

        if land or builders or houses:
            bm = {}
            if land:
                bm["land"] = land
            if builders:
                bm["builders"] = builders
            if houses:
                bm["houses"] = houses
            bm["note"] = "curated buyer outreach list (no published buy box; contact to assign)"
            raw["buyer_match"] = bm
            li.raw = raw
            stats["matched"] += 1
            if land or builders:
                stats["land"] += 1
            if houses:
                stats["houses"] += 1
    return stats
