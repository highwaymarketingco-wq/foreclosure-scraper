"""Buyer-match tagger — surface the real, active buyers who want a lead's
property, grouped by buyer type, so a card shows "who to flip this to" (LOCAL).

Backed by data/land_buyers.json — 188 named, actively-acquiring buyers across
the footprint from the buyer-universe sweep (production + regional homebuilders,
land developers, multifamily, commercial, industrial/I-85 logistics, self-
storage, solar/utility-scale, manufactured-housing, timber/recreational,
conservation trusts, economic-development). Plus the direct "we buy land" flip
companies as an outreach lane.

Match = region (WNC vs Upstate-SC) ∩ property category (land / multifamily /
commercial / residential). Land is where most demand sits, so a vacant-land
card surfaces developers, builders, timber, solar (rural), conservation (rural),
manufactured-housing, econ-dev, and — on the I-85 corridor — industrial. Writes
raw['buyer_match'] = {by_type:{type:[{name,contact,buys}]}, count, note}, capped
per type so the card stays readable. Gate BUYER_MATCH=0.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from .models import Listing

_ENABLED = os.environ.get("BUYER_MATCH") != "0"
_CAP_PER_TYPE = int(os.environ.get("BUYER_MATCH_CAP", "4"))
_DATA = Path(__file__).resolve().parent / "data" / "land_buyers.json"

_WNC = {"Buncombe", "Henderson", "Rutherford", "McDowell", "Cleveland", "Polk",
        "Gaston", "Lincoln", "Burke", "Transylvania", "Mitchell", "Madison"}
_UPSTATE = {"Greenville", "Spartanburg", "Anderson", "Pickens", "Oconee",
            "Cherokee", "Union", "Laurens"}
_I85 = {"Spartanburg", "Greenville", "Cherokee", "Anderson", "Gaston"}

_LAND_KINDS = {"land", "vacant_land", "vacant", "lot", "acreage"}

# Which buyer types want which property category.
_LAND_TYPES = {"residential_land_developers", "production_homebuilders",
               "regional_local_builders", "timber_recreational",
               "solar_utility_land", "conservation_trusts",
               "manufactured_housing", "econ_dev_municipal"}
_MF_TYPES = {"multifamily_developers"}
_COMMERCIAL_TYPES = {"commercial_retail_office", "industrial_logistics", "self_storage"}

# Direct "we buy land" flip companies (fast cash, whole-footprint) — the outreach lane.
_LAND_FLIPPERS = [
    {"name": "Bubba Land Company", "contact": "https://bubba-land.com/", "buys": "rural acreage 3+ ac, outside city limits", "min_acres": 3.0},
    {"name": "Value Land Buyers", "contact": "https://www.valuelandbuyers.com/", "buys": "raw land + vacant lots, any size"},
    {"name": "Selling Land Fast", "contact": "https://www.sellinglandfast.com/", "buys": "rural acreage, raw land, lots, farms"},
]
_HOUSE_BUYERS = [
    {"name": "HomeVestors / We Buy Ugly Houses", "contact": "https://www.webuyuglyhouses.com/", "buys": "cash for houses, blanket coverage"},
    {"name": "Greenville Home Solutions", "contact": "https://www.greenvillehomesolutions.com/", "buys": "houses + land, Upstate SC", "region": "upstate_sc"},
]

_REGISTRY: list | None = None


def _load() -> list:
    global _REGISTRY
    if _REGISTRY is None:
        try:
            _REGISTRY = json.loads(_DATA.read_text()).get("buyers", [])
        except Exception:
            _REGISTRY = []
    return _REGISTRY


def _region(county: str) -> str | None:
    if county in _WNC:
        return "wnc"
    if county in _UPSTATE:
        return "upstate_sc"
    return None


def _is_land(li: Listing) -> bool:
    pk = (li.property_kind.value if hasattr(li.property_kind, "value") else str(li.property_kind or "")).lower()
    if any(k in pk for k in _LAND_KINDS):
        return True
    d = (li.description or "").lower()
    return "vacant lot" in d or "vacant land" in d or "vacant parcel" in d


def _is_mf(li: Listing) -> bool:
    pk = (li.property_kind.value if hasattr(li.property_kind, "value") else str(li.property_kind or "")).lower()
    return "multi" in pk or "apartment" in pk or bool((li.raw or {}).get("multifamily_class"))


def _is_commercial(li: Listing) -> bool:
    pk = (li.property_kind.value if hasattr(li.property_kind, "value") else str(li.property_kind or "")).lower()
    return "commercial" in pk or "retail" in pk or "office" in pk or "industrial" in pk


def _acres(li: Listing):
    raw = li.raw if isinstance(li.raw, dict) else {}
    for src in (raw.get("lrcpwa"), raw.get("gis"), raw):
        if isinstance(src, dict):
            for k in ("acreage", "acres", "calculatedAcres", "deededAcres"):
                try:
                    if src.get(k) is not None:
                        return float(str(src[k]).replace(",", ""))
                except (TypeError, ValueError):
                    pass
    return None


def enrich_buyer_match(listings: Iterable[Listing]) -> dict:
    stats = {"matched": 0, "by_category": {}}
    if not _ENABLED:
        return stats
    reg = _load()
    for li in listings:
        county = (li.county or "").replace(" County", "").strip().title()
        region = _region(county)
        if not region:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        is_land = _is_land(li)
        is_mf = _is_mf(li)
        is_comm = _is_commercial(li)
        acres = _acres(li)

        # which buyer types apply to this lead
        if is_land:
            want_types = set(_LAND_TYPES)
            if county in _I85:
                want_types.add("industrial_logistics")
            category = "land"
        elif is_mf:
            want_types = set(_MF_TYPES); category = "multifamily"
        elif is_comm:
            want_types = set(_COMMERCIAL_TYPES); category = "commercial"
        else:
            want_types = set(); category = "residential"

        by_type: dict[str, list] = {}
        for b in reg:
            bt = b.get("type")
            if bt not in want_types:
                continue
            if region not in (b.get("regions") or []):
                continue
            # keep solar/timber/conservation to genuinely rural (skip dense metro city lots)
            if bt in ("solar_utility_land",) and acres is not None and acres < 5:
                continue
            by_type.setdefault(bt, [])
            if len(by_type[bt]) < _CAP_PER_TYPE:
                by_type[bt].append({"name": b.get("name"), "contact": b.get("contact"), "buys": b.get("buys")})

        # direct land-flip + house-buyer outreach lanes
        if is_land:
            flip = [f for f in _LAND_FLIPPERS if not (f.get("min_acres") and acres is not None and acres < f["min_acres"])]
            if flip:
                by_type["land_flippers"] = [{"name": f["name"], "contact": f["contact"], "buys": f["buys"]} for f in flip]
        elif category == "residential" and (raw.get("distress_stack") or {}).get("tier") in ("HOT", "WARM"):
            houses = [h for h in _HOUSE_BUYERS if h.get("region") in (None, region)]
            if houses:
                by_type["house_buyers"] = [{"name": h["name"], "contact": h["contact"], "buys": h["buys"]} for h in houses]

        if by_type:
            cnt = sum(len(v) for v in by_type.values())
            raw["buyer_match"] = {"by_type": by_type, "count": cnt, "category": category,
                                  "note": "active buyers by type + county (outreach — no published buy box)"}
            li.raw = raw
            stats["matched"] += 1
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
    return stats
