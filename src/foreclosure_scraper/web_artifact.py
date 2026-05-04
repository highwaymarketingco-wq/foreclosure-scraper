"""Generate the static-site JSON files consumed by docs/index.html (the live dashboard).

Writes:
  docs/listings.json   — array of sanitized listings (Pydantic-dumped, raw kept slim)
  docs/run_meta.json   — run timestamp, source_status, totals, sources contributing
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import structlog

from .models import Listing

log = structlog.get_logger()


# Whitelist of `raw` sub-keys to keep in the output (keep file small + privacy-OK)
RAW_KEEP = {
    "gis": ("owner", "mailing", "last_sale"),
    "zillow": ("zpid", "homeType", "zestimate", "yearBuilt", "bedrooms", "bathrooms",
               "livingArea", "lotSize", "taxAssessedValue", "description", "photo", "photos"),
    "flags": "*",
    "assessment": "*",
    "calc": "*",      # ARV / rehab / max_bid / ROI / cash-on-cash
    "grade": "*",     # A-F per-dimension + overall
    "location": ("median_household_income", "median_home_value",
                 "owner_occupied_pct", "unemployment_pct"),
    "comps": "*",                     # 3 sold comps per listing (HomeHarvest)
    "rent_comps": "*",                # 3 rent comps per listing (HomeHarvest)
    "comps_note": "*",                # explanation when no like-for-like found
    "comp_median_ppsf": "*",
    "condition_tier": "*",            # move_in_ready / cosmetic / major / gut
    "condition_source": "*",          # "vision-HIGH" / "vision-MEDIUM" / regex/age default
    "vision": "*",                    # full Claude Vision condition report
    "rent_median_ppsf": "*",
    "estimated_monthly_rent": "*",
    "rod_docs": "*",                  # ROD recorded documents (deeds, mortgages, satisfactions)
    "lien_priority": "*",             # senior/junior liens + super-priority warnings
    "propwire": "*",                  # equity, owner, last sale (when present)
    "loopnet": "*",                   # multifamily-specific cap rate, units, etc.
    "images": "*",                    # {primary, map, street} fallback image map
    "flood": "*",                     # FEMA flood-zone tag {zone, in_sfha, ...}
    "nod": "*",                       # ROD-discovered Notice of Default
    "bankruptcy": "*",                # CourtListener bankruptcy match on defendant name
    "courtlistener": "*",             # raw bankruptcy docket data when emitted as a listing
    "distressed": "*",                # HomeHarvest distressed-keyword matches
    "epa": "*",                       # EPA ECHO environmental hazards
    "crime": "*",                     # FBI UCR / per-zip crime stats
    "schools": "*",                   # GreatSchools per-address ratings (when key set)
    "walk_score": "*",                # Walk Score per-address (when key set)
}


def _slim_raw(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, keep in RAW_KEEP.items():
        v = raw.get(k)
        if v is None:
            continue
        if keep == "*":
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {sk: v[sk] for sk in keep if sk in v}
    return out


def _to_dict(li: Listing) -> dict:
    d = li.model_dump(mode="json", exclude_none=False)
    # Trim raw payload
    d["raw"] = _slim_raw(li.raw)
    # Drop legal_description from public view (often huge)
    if "legal_description" in d and d["legal_description"]:
        d["legal_description"] = d["legal_description"][:200]
    return d


def write_artifact(
    listings: list[Listing],
    summary: dict,
    docs_dir: Path | str = "docs",
) -> tuple[Path, Path]:
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)

    listings_path = docs / "listings.json"
    meta_path = docs / "run_meta.json"

    payload = [_to_dict(li) for li in listings]
    listings_path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")

    meta = {
        "run_time": datetime.utcnow().isoformat() + "Z",
        "total": len(listings),
        "by_source": summary.get("by_source", {}),
        "by_state": summary.get("by_state", {}),
        "by_county_top": summary.get("by_county_top", []),
        "source_status": summary.get("source_status", {}),
        "regressions": summary.get("regressions", []),
        "errors": summary.get("errors", []),
        "notes": summary.get("notes", ""),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, default=str, indent=2), encoding="utf-8")

    log.info("web_artifact.written", listings=len(listings), bytes=listings_path.stat().st_size)
    return listings_path, meta_path
