"""Recorded-sales comps — value a property from ACTUAL nearby arms-length
recorded sales pulled live from the county GIS, distance-matched to the subject.

This is the comp-accuracy fix: instead of scraped Realtor listings matched by
zip (list-vs-sold gap, coarse geography), we query the county parcel layer for
real recorded sales within a radius of the subject's coordinates, of comparable
size, and compute a median $/sqft. That $/sqft × the subject's sqft is the
highest-confidence ARV input (Tier 0 in valuation/calc.py).

Per-county field config (price/date/sqft field names + the working date-filter
syntax + spatial support) was live-verified against each county's ArcGIS layer.
Counties whose layer carries no heated-sqft field are listed sqft=None and skip
the $/sqft path until a CAMA sqft join is wired (Pass-2 follow-up).
"""
from __future__ import annotations

from statistics import median
from typing import Optional

import structlog

from .enrichment_owner_mailing import COUNTY_GIS
from .http_client import client
from .models import Listing

log = structlog.get_logger()

# (state, county) -> field config. Layer URL comes from COUNTY_GIS[f"{state}:{county}"].
# date_kind: how the sale-date field must be filtered:
#   "date"     -> ArcGIS DATE literal:  FIELD > DATE 'YYYY-MM-DD'   (epoch-ms FAILS)
#   "year"     -> integer year field:   FIELD >= YYYY
#   "yyyymm"   -> string YYYYMM:        FIELD >= 'YYYYMM'
#   "yyyymmdd" -> string YYYYMMDD:      FIELD >= 'YYYYMMDD'
RECORDED_COMP_CONFIG: dict[tuple[str, str], dict] = {
    ("NC", "Burke"):        {"price": "Sale_Value",     "date": "Sale_Date",     "date_kind": "date",     "sqft": "Heated_Area",   "since": "2019-01-01"},
    ("NC", "Gaston"):       {"price": "SALESAMT",        "date": "SALEDATE",      "date_kind": "date",     "sqft": "SQFT",          "since": "2023-01-01"},
    ("NC", "Henderson"):    {"price": "PKG_SALE_PRICE",  "date": "PKG_SALE_DATE", "date_kind": "date",     "sqft": "HEATED_AREA",   "since": "2023-01-01", "buffer_ft": 10560},
    ("NC", "Lincoln"):      {"price": "SALEPRICE",       "date": "DEEDYR",        "date_kind": "year",     "sqft": "MAINAREASQFT",  "since": 2023},
    ("NC", "Rutherford"):   {"price": "Sale_Price",      "date": "Deed_Date",     "date_kind": "date",     "sqft": "Heated_Area",   "since": "2023-01-01"},
    ("NC", "Transylvania"): {"price": "SALE_PRICE",      "date": "SALE_DATE",     "date_kind": "yyyymm",   "sqft": "HEATED_SQ_",    "since": "202301"},
    # SC layers carry price+date+geometry but NO heated-sqft on the owner layer.
    # Kept here (sqft=None) so the engine is ready the moment a CAMA sqft join lands.
    ("SC", "Pickens"):      {"price": "SALEP",           "date": "SALEDT",        "date_kind": "date",     "sqft": None,            "since": "2023-01-01"},
    ("SC", "Spartanburg"):  {"price": "SaleAmount",      "date": "SaleDate",      "date_kind": "date",     "sqft": None,            "since": "2023-01-01"},
    ("SC", "Laurens"):      {"price": "Sale_Price",      "date": "Sale_Date",     "date_kind": "yyyymmdd", "sqft": None,            "since": "20230101"},
}

_DEFAULT_BUFFER_FT = 5280       # 1 mile
_MIN_ARMS_LENGTH = 10000        # exclude $1 / nominal family transfers
_MIN_SQFT = 200                 # exclude land / outbuildings
_PPSF_FLOOR, _PPSF_CEIL = 20.0, 800.0   # drop garbage $/sqft
_MIN_COMPS_HIGH = 5             # >= this many comps -> HIGH confidence


def _date_clause(cfg: dict) -> str:
    f, kind, since = cfg["date"], cfg["date_kind"], cfg["since"]
    if kind == "date":
        return f"{f} > DATE '{since}'"
    if kind == "year":
        return f"{f} >= {since}"
    return f"{f} >= '{since}'"   # yyyymm / yyyymmdd string compare


def _where(cfg: dict) -> str:
    parts = [f"{cfg['price']} > {_MIN_ARMS_LENGTH}", _date_clause(cfg)]
    if cfg.get("sqft"):
        parts.append(f"{cfg['sqft']} > {_MIN_SQFT}")
    return " AND ".join(parts)


def _ppsf_list(features: list[dict], cfg: dict) -> list[float]:
    price_f, sqft_f = cfg["price"], cfg.get("sqft")
    if not sqft_f:
        return []
    out: list[float] = []
    for feat in features:
        a = feat.get("attributes", {})
        price = a.get(price_f)
        sqft = a.get(sqft_f)
        if not price or not sqft or sqft <= _MIN_SQFT or price <= _MIN_ARMS_LENGTH:
            continue
        ppsf = float(price) / float(sqft)
        if _PPSF_FLOOR <= ppsf <= _PPSF_CEIL:
            out.append(round(ppsf, 2))
    return sorted(out)


async def _query_comps(http, base: str, lat: float, lon: float, cfg: dict) -> list[dict]:
    buffer_ft = cfg.get("buffer_ft", _DEFAULT_BUFFER_FT)
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
        "distance": str(buffer_ft), "units": "esriSRUnit_Foot",
        "spatialRel": "esriSpatialRelIntersects", "where": _where(cfg),
        "outFields": ",".join(x for x in (cfg["price"], cfg.get("sqft")) if x),
        "returnGeometry": "false", "resultRecordCount": "200", "f": "json",
    }
    r = await http.get(base.rstrip("/") + "/query", params=params, timeout=45.0)
    if r.status_code != 200:
        return []
    j = r.json()
    if "error" in j:
        log.warning("recorded_comps.query_error", msg=str(j["error"].get("message"))[:80])
        return []
    return j.get("features", []) or []


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    i = max(0, min(len(vals) - 1, int(round(p * (len(vals) - 1)))))
    return vals[i]


async def enrich(listings: list[Listing]) -> list[Listing]:
    """Attach recorded-sales comps (median $/sqft from real nearby transactions)."""
    targets = [li for li in listings
               if li.latitude and li.longitude
               and (li.state, li.county) in RECORDED_COMP_CONFIG
               and RECORDED_COMP_CONFIG[(li.state, li.county)].get("sqft")]
    if not targets:
        return listings
    # group by county so we open one client and reuse the host connection
    by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in targets:
        by_county.setdefault((li.state, li.county), []).append(li)
    enriched_n = 0
    try:
        async with client(timeout=60.0) as http:
            for (state, county), group in by_county.items():
                cfg = RECORDED_COMP_CONFIG[(state, county)]
                base = COUNTY_GIS.get(f"{state}:{county}", {}).get("url")
                if not base:
                    continue
                for li in group:
                    try:
                        feats = await _query_comps(http, base, li.latitude, li.longitude, cfg)
                    except Exception:
                        log.warning("recorded_comps.failed", county=county)
                        continue
                    ppsf = _ppsf_list(feats, cfg)
                    if len(ppsf) < 3:
                        continue
                    raw = li.raw if isinstance(li.raw, dict) else {}
                    med = round(median(ppsf), 2)
                    raw["recorded_comps"] = {
                        "median_ppsf": med,
                        "count": len(ppsf),
                        "p25_ppsf": _percentile(ppsf, 0.25),
                        "p75_ppsf": _percentile(ppsf, 0.75),
                        "radius_mi": round(cfg.get("buffer_ft", _DEFAULT_BUFFER_FT) / 5280, 1),
                        "confidence": "HIGH" if len(ppsf) >= _MIN_COMPS_HIGH else "MEDIUM",
                        "source": "county_gis_recorded_sales",
                    }
                    raw["comp_median_ppsf_recorded"] = med
                    li.raw = raw
                    enriched_n += 1
    except Exception:
        log.warning("recorded_comps.enrich_aborted")
        return listings
    log.info("recorded_comps.done", enriched=enriched_n, candidates=len(targets))
    return listings
