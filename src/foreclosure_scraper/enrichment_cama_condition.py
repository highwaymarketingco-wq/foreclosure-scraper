"""Near-universal property-CONDITION layer from county assessor/CAMA tables.

Pulls the per-parcel CONDITION + GRADE + YearBuilt the appraiser recorded and
PIN-joins it to our leads. This is the one field the bulk parcel/GIS feeds and
the SCDOT shared service almost never expose, yet it's the single strongest
tell of a distressed structure: a "Poor" / "Unsound" appraiser condition rating
is the appraiser's own note that the house is falling down.

Unlike the per-parcel qPublic card path (enrichment_assessor_card, a ~30s-3min
browser render per subject, capped at a few hundred), this is a BULK, free,
open ArcGIS-REST layer per county: one batched ``PIN IN (...)`` query returns
condition for ~100 leads at a time. No CAPTCHA, no login, no render — friendly
ArcGIS Online / county FeatureServer JSON.

Coverage (live-verified 2026-07-02, all open ArcGIS-REST JSON):

  * Buncombe NC  — Real Estate Appraisal Residential Building 2024 (hosted CAMA
                   TABLE, services6.arcgis.com). 96,633 res building records;
                   Condition N/G/R/F/P/U + Grade A-E/S/L + YearBuilt. PIN15.
  * Carteret NC  — county parcel MapServer carries Condition (Average/Good/Fair/
                   Poor/Very Poor/Unsound/Excellent/Very Good) + Grade +
                   GradeAndCDU + Y_BLT_HOUSE. PIN15.
  * Onslow NC    — county parcel MapServer carries YEARBUILT (COM_GRADE is a
                   COMMERCIAL grade, null for residential — year only).
  * York SC      — hosted Parcels FeatureServer carries YearBuilt + FinishedSQFT
                   + HOMESTEAD (no bulk Condition/Grade in SC — see below).

SC condition note: SC counties gate per-parcel CONDITION behind qPublic cards
(per-parcel render, handled by enrichment_assessor_card's render-class path).
No SC county in our footprint exposes a bulk ArcGIS Condition column — SCDOT's
shared layer carries at most YearBuilt (York/Beaufort) or a numeric RESGRADE
(Greenville). So for SC this enricher stamps YearBuilt where available and the
Condition/Grade half of the SC ask stays on the qPublic/GATHER path. York SC is
the SC layer live-verified here (YearBuilt fills; Condition intentionally absent).

Stamps ``raw['condition_cama'] = {condition, condition_code, grade, year_built,
source}`` and, when the appraiser condition is a distressed tier (Poor / Very
Poor / Unsound / Dilapidated), sets ``raw['distressed'] = True`` (which
distress_score reads as a PROPERTY signal) and fills ``raw['condition_tier']``
(major/gut) ONLY when a stronger signal — Vision or comps text — has not already
set it. Also backfills Listing.year_built when missing. Fills only missing
fields; never overwrites a Vision-grounded condition_tier or a real year_built.

OFF by default is NOT used here — it's a pure batched-JSON pass (cheap + safe),
so it runs in the normal enrichment chain like enrich_gis_attrs. It must run
AFTER parcel_id is populated (parcel_lookup / gis_attrs) and BEFORE the
calc/grade + distress_score pass so the year_built + distressed flag feed
valuation. Wiring lives in main.py / merge_today_sources.py / regenerate_
dashboard.py (documented in the module footer); do NOT wire it in _registry.py.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()


# ---- Per-county CAMA condition source map ----------------------------------------
#
# Each entry is one open ArcGIS-REST query endpoint plus the field names that
# carry condition / grade / year, and how to build the PIN join key from a
# lead's parcel_id. join="pin" batches a ``PIN IN (...)`` query (efficient);
# join="address" falls back to a per-lead street LIKE (only for leads with no
# parcel_id). pin_pad15=True zero-extends a 10-digit short PIN to the 15-digit
# stored key (Buncombe/Carteret store PIN15 = shortpin + '00000').

CAMA_SOURCES: dict[tuple[str, str], dict[str, Any]] = {
    ("NC", "Buncombe"): {
        # Hosted CAMA residential-building TABLE (no geometry) — PIN join only.
        "url": "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
               "Real Estate Appraisal Residential Building 2024/FeatureServer/0",
        "pin_field": "PIN",
        "condition_field": "Condition",
        "grade_field": "Grade",
        "year_field": "YearBuilt",
        "join": "pin",
        "pin_pad15": True,
    },
    ("NC", "Carteret"): {
        # County parcel MapServer — Condition spelled out (Average/Good/Poor/...).
        "url": "https://arcgisweb.carteretcountync.gov/arcgis/rest/services/"
               "Layers/Parceldata/MapServer/0",
        "pin_field": "PIN15",
        "condition_field": "Condition",
        "grade_field": "Grade",
        "year_field": "Y_BLT_HOUSE",
        "join": "pin",
        "pin_pad15": True,
    },
    ("NC", "Onslow"): {
        # COM_GRADE is a commercial grade (null for residential); year only.
        "url": "https://maps.onslowcountync.gov/arcgis/rest/services/"
               "GISWebsite/GISWebsiteLayers/MapServer/7",
        "pin_field": "PIN",
        "condition_field": None,
        "grade_field": None,
        "year_field": "YEARBUILT",
        "join": "pin",
        "pin_pad15": False,
    },
    ("SC", "York"): {
        # SC bulk layer: YearBuilt only (no bulk Condition/Grade in SC).
        "url": "https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/"
               "Parcels/FeatureServer/0",
        "pin_field": "ParcelID",
        "condition_field": None,
        "grade_field": None,
        "year_field": "YearBuilt",
        "join": "pin",
        "pin_pad15": False,
    },
}

# Property kinds with no building the appraiser rates — skip (raw land).
_NO_STRUCTURE_KINDS = {PropertyKind.LAND}

# How many PINs to pack into one ``PIN IN (...)`` batch. ArcGIS accepts long
# where-clauses; 100 keeps each URL well under any gateway length limit.
_PIN_BATCH = 100

# ---- Condition normalization -----------------------------------------------------
#
# Every county spells condition differently — single-letter codes (Buncombe:
# P/F/U/N/G/R), full words (Carteret: Poor/Very Poor/Unsound/Fair/Average/...).
# Map both to a canonical label + a distressed flag. The distressed set mirrors
# enrichment_owner_mailing._POOR_CONDITION so the two condition lanes agree.

_CANON = {
    # code / word (upper)        -> (canonical label, distressed?)
    "P": ("poor", True), "POOR": ("poor", True),
    "VP": ("very_poor", True), "VERY POOR": ("very_poor", True),
    "U": ("unsound", True), "UN": ("unsound", True), "UNSOUND": ("unsound", True),
    "UNSAFE": ("unsound", True),
    "DL": ("dilapidated", True), "DILAPIDATED": ("dilapidated", True),
    "BAD": ("poor", True),
    "F": ("fair", False), "FR": ("fair", False), "FA": ("fair", False),
    "FAIR": ("fair", False),
    "A": ("average", False), "AV": ("average", False), "AVG": ("average", False),
    "AVERAGE": ("average", False), "N": ("average", False), "NORMAL": ("average", False),
    "G": ("good", False), "GD": ("good", False), "GOOD": ("good", False),
    "VG": ("very_good", False), "VERY GOOD": ("very_good", False),
    "R": ("good", False),  # Buncombe R = Restored/Remodeled -> not distressed
    "E": ("excellent", False), "EX": ("excellent", False), "EXCELLENT": ("excellent", False),
}


def _normalize_condition(raw_val: Any) -> tuple[str | None, bool]:
    """(canonical_label, distressed) from a county condition code/word, or (None, False)."""
    if raw_val is None:
        return None, False
    key = str(raw_val).strip().upper()
    if not key or key in ("<NULL>",):
        return None, False
    canon = _CANON.get(key)
    if canon:
        return canon
    # Unknown code: keep the raw label (lower) but don't guess distress.
    return key.lower(), False


def _pin_key(parcel_id: str | None, pad15: bool) -> str | None:
    """Build the county's stored PIN from a lead's parcel_id.

    Digits only. When the layer stores 15-digit PIN15 (short 10-digit pin +
    '00000') and the lead carries the 10-digit short form, zero-extend it.
    """
    if not parcel_id:
        return None
    digits = re.sub(r"\D", "", str(parcel_id))
    if not digits:
        return None
    if pad15 and len(digits) == 10:
        return digits + "00000"
    return digits


def _year_int(val: Any) -> int | None:
    try:
        y = int(str(val)[:4])
    except (ValueError, TypeError):
        return None
    return y if 1800 < y < 2035 else None


# ---- Core ArcGIS batch fetch -----------------------------------------------------


async def _fetch_by_pins(
    c: httpx.AsyncClient, cfg: dict[str, Any], pins: list[str]
) -> dict[str, dict[str, Any]]:
    """Batched ``PIN IN (...)`` query. Returns {pin: {condition,grade,year}}."""
    out: dict[str, dict[str, Any]] = {}
    base = cfg["url"].rstrip("/") + "/query"
    pin_field = cfg["pin_field"]
    out_fields = ",".join(
        f for f in (pin_field, cfg.get("condition_field"), cfg.get("grade_field"),
                    cfg.get("year_field")) if f
    )
    for i in range(0, len(pins), _PIN_BATCH):
        chunk = pins[i:i + _PIN_BATCH]
        quoted = ",".join("'" + p.replace("'", "''") + "'" for p in chunk)
        params = {
            "where": f"{pin_field} IN ({quoted})",
            "outFields": out_fields,
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            r = await c.get(base, params=params, timeout=30.0)
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
        except (httpx.HTTPError, ValueError):
            continue
        for feat in data.get("features", []):
            attrs = feat.get("attributes") or {}
            pin = attrs.get(pin_field)
            if pin is None:
                continue
            key = re.sub(r"\D", "", str(pin))
            # Prefer the record that actually has a building condition/grade over
            # a bare parcel row (a PIN can have >1 building card).
            rec = {
                "condition": attrs.get(cfg["condition_field"]) if cfg.get("condition_field") else None,
                "grade": attrs.get(cfg["grade_field"]) if cfg.get("grade_field") else None,
                "year": attrs.get(cfg["year_field"]) if cfg.get("year_field") else None,
            }
            prev = out.get(key)
            if prev is None or (rec["condition"] and not prev.get("condition")):
                out[key] = rec
    return out


async def _fetch_by_address(
    c: httpx.AsyncClient, cfg: dict[str, Any], street: str
) -> dict[str, Any] | None:
    """Per-lead street-LIKE fallback for a lead with no parcel_id (rare)."""
    from .enrichment_arcgis import _street_keywords  # reuse tested tokenizer

    keyword = _street_keywords(street)
    if not keyword:
        return None
    base = cfg["url"].rstrip("/") + "/query"
    # A county parcel layer with a Condition column still needs an address field;
    # detect it lazily from the layer schema (cheap, cached by ArcGIS-side).
    addr_field = cfg.get("addr_field")
    if not addr_field:
        from .enrichment_arcgis import _detect_addr_field
        addr_field = await _detect_addr_field(c, base)
        cfg["addr_field"] = addr_field  # memoize on the cfg for the run
    if not addr_field:
        return None
    pat = f"%{keyword}%".replace("'", "''")
    params = {
        "where": f"UPPER({addr_field}) LIKE UPPER('{pat}')",
        "outFields": ",".join(
            f for f in (cfg.get("condition_field"), cfg.get("grade_field"),
                        cfg.get("year_field")) if f
        ) or "*",
        "returnGeometry": "false",
        "resultRecordCount": "1",
        "f": "json",
    }
    try:
        r = await c.get(base, params=params, timeout=30.0)
        if r.status_code != 200:
            return None
        data = r.json()
        feats = data.get("features") or []
        if not feats:
            return None
        attrs = feats[0].get("attributes") or {}
        return {
            "condition": attrs.get(cfg["condition_field"]) if cfg.get("condition_field") else None,
            "grade": attrs.get(cfg["grade_field"]) if cfg.get("grade_field") else None,
            "year": attrs.get(cfg["year_field"]) if cfg.get("year_field") else None,
        }
    except (httpx.HTTPError, ValueError):
        return None


# ---- Apply -----------------------------------------------------------------------


def _distressed_tier(condition_label: str | None) -> str | None:
    """Map a distressed CAMA condition to a condition_tier bucket (major/gut).

    Used only to SEED condition_tier when nothing stronger set it. Unsound /
    Dilapidated -> gut; Poor / Very Poor -> major.
    """
    if condition_label in ("unsound", "dilapidated"):
        return "gut"
    if condition_label in ("poor", "very_poor"):
        return "major"
    return None


def _apply(li: Listing, rec: dict[str, Any], source: str, stats: dict) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    label, distressed = _normalize_condition(rec.get("condition"))
    grade = rec.get("grade")
    if isinstance(grade, str):
        grade = grade.strip() or None
    year = _year_int(rec.get("year"))

    if label is None and grade is None and year is None:
        return  # nothing usable

    block: dict[str, Any] = {"source": source}
    if label is not None:
        block["condition"] = label
        block["condition_code"] = str(rec.get("condition")).strip()
        block["distressed"] = distressed
    if grade is not None:
        block["grade"] = grade
    if year is not None:
        block["year_built"] = year
    li.raw["condition_cama"] = block
    stats["stamped"] += 1

    # Backfill Listing.year_built when missing (feeds rehab/age heuristics).
    if year is not None and not li.year_built:
        li.year_built = year
        stats["filled_year"] += 1

    # Feed the distress/condition tier — but never clobber a stronger signal.
    if distressed:
        # raw['distressed']=True is what distress_score reads as a PROPERTY tell.
        cur = li.raw.get("distressed")
        if cur in (None, False):
            li.raw["distressed"] = True
        stats["distressed"] += 1
        # Seed condition_tier ONLY if nothing (Vision/comps) already set it.
        vt = None
        vis = li.raw.get("vision")
        if isinstance(vis, dict):
            vt = vis.get("condition_tier")
        if not vt and not li.raw.get("condition_tier"):
            tier = _distressed_tier(label)
            if tier:
                li.raw["condition_tier"] = tier
                li.raw["condition_source"] = "cama"
                stats["seeded_tier"] += 1


def _has_structure(li: Listing) -> bool:
    return li.property_kind not in _NO_STRUCTURE_KINDS


def _county_key(li: Listing) -> tuple[str, str] | None:
    if not li.state or not li.county:
        return None
    county = li.county.replace(" County", "").strip()
    for suffix in (", NC", ", SC", ",NC", ",SC"):
        if county.upper().endswith(suffix):
            county = county[: -len(suffix)].strip()
    county = county.split(",")[0].strip()
    return (li.state, county)


# ---- Public API ------------------------------------------------------------------


async def enrich_cama_condition(listings: list[Listing], concurrency: int = 6) -> dict:
    """Stamp raw['condition_cama'] (condition+grade+year) on every lead in a
    county with a bulk CAMA-condition layer, PIN-joined. Pure batched ArcGIS
    JSON — free, fast, compliant. Fills missing fields only."""
    stats = {"eligible": 0, "matched": 0, "stamped": 0, "filled_year": 0,
             "distressed": 0, "seeded_tier": 0, "counties": 0}

    # Bucket leads by county source.
    by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        key = _county_key(li)
        if key is None or key not in CAMA_SOURCES:
            continue
        if not _has_structure(li):
            continue
        by_county.setdefault(key, []).append(li)
    if not by_county:
        return stats
    stats["counties"] = len(by_county)
    stats["eligible"] = sum(len(v) for v in by_county.values())

    sem = asyncio.Semaphore(concurrency)

    async def _do_county(c: httpx.AsyncClient, key: tuple[str, str],
                         leads: list[Listing]) -> None:
        cfg = CAMA_SOURCES[key]
        source = f"cama:{key[0]}:{key[1]}"
        pad15 = cfg.get("pin_pad15", False)
        # PIN-join batch for leads that have a parcel_id.
        pin_map: dict[str, list[Listing]] = {}
        no_pin: list[Listing] = []
        for li in leads:
            pk = _pin_key(li.parcel_id, pad15)
            if pk:
                pin_map.setdefault(pk, []).append(li)
            elif li.street_address:
                no_pin.append(li)
        async with sem:
            if pin_map and cfg.get("join") == "pin":
                got = await _fetch_by_pins(c, cfg, list(pin_map.keys()))
                for pk, rows in got.items():
                    for li in pin_map.get(pk, []):
                        stats["matched"] += 1
                        _apply(li, rows, source, stats)
            # Address fallback (only leads with no parcel_id).
            for li in no_pin:
                rec = await _fetch_by_address(c, cfg, li.street_address)
                if rec:
                    stats["matched"] += 1
                    _apply(li, rec, source, stats)

    async with client(timeout=30.0) as c:
        await asyncio.gather(*(_do_county(c, k, v) for k, v in by_county.items()))

    log.info("enrichment.cama_condition.done", **stats)
    return stats


# ---- Wiring (report — do NOT edit _registry.py / main.py in this module) ----------
#
# enrich_cama_condition is async and belongs in the async enrichment phase,
# AFTER parcel_id is populated (enrich_with_parcel_lookup / enrich_gis_attrs)
# and BEFORE the calc/grade + distress_score pass. Add, in each orchestrator:
#
#   from foreclosure_scraper.enrichment_cama_condition import enrich_cama_condition
#
#   # main.py — right after the enrich_gis_attrs(enriched) call (~line 897):
#   await enrich_cama_condition(enriched)
#
#   # scripts/merge_today_sources.py — in _resolve(), right after the
#   # "gis_attrs" _step (~line 216):
#   await _step("cama_condition", enrich_cama_condition(merged, concurrency=6))
#
#   # scripts/regenerate_dashboard.py — right after the "gis_attrs" bounded run
#   # (~line 98), before enrich_sc_cama:
#   _run_bounded("cama_condition", enrich_cama_condition(listings, concurrency=6),
#                _t("REGEN_CAMA_COND_TIMEOUT", 3600))
#
# It reads raw['distressed'] (distress_score PROPERTY signal) and Listing.year_
# built, so placing it before calc/grade lets the fresh signals grade correctly.
