"""Macon County NC gis.maconnc.org ArcGIS REST "TemplateSite/TaxParcels" MapServer, layer 0 --
raw['rollback_exposure'] from its own DEFERMENT field.

WHY THIS EXISTS (round 18 of the tax-cluster gap_matrix sweep, 2026-11-17). Round 17's own note
said Macon "load[s] real, substantial county tax/GIS pages; the specific search tool wasn't
isolated within the time this round had left." Found this round: gis.maconnc.org/arcgis/rest/
services (a live, open, unauthenticated ArcGIS REST directory) -> TemplateSite/TaxParcels/
MapServer/0 ("Tax Parcels"), whose own field list carries DEFERMENT, a present-use-deferred
assessment amount -- the SAME present-use-rollback shape already confirmed this round for
Davidson (enrichment_davidson_rollback_exposure.py) and Craven
(scrapers/counties_nc/craven_tax_table.py, layer 6). Live-confirmed real, nonzero values
2026-11-17: 1,275 of this layer's parcels carry DEFERMENT > 0, e.g. PIN "6468452250", owner
"THE COPE FAMILY LIMITED PATNERSHIP I", DEFERMENT $328,040 of $352,350 LAND_VALUE (arithmetic
checks: ASSESSED_VALUE = LAND_VALUE - DEFERMENT exactly on every sampled row).

PARCEL JOIN. This layer's own `PIN` field is ALREADY the board's bare-digit parcel_id, no
transform needed (live-confirmed against 5 real Macon board rows, e.g. board parcel_id
"7540038288" -- a bare 10-digit run, same shape as this layer's PIN column; a `_compact_pid()`
strip is still applied defensively, same convention as the Craven/Davidson siblings, in case a
future row carries a dashed form).

BULK, not per-row: queried ONCE per run (paginated, resultOffset in steps of 1000, server-side
filtered to DEFERMENT > 0 so the real page count stays tiny -- 1,275 rows, well under one page
at this vendor's own maxRecordCount) and joined locally against the board's already-known Macon
NC rows. Free, public, no login, no CAPTCHA/WAF.

WHAT THIS DOES NOT COVER. This layer carries no balance-due/tax-year history field at all (only
CAMA value fields: Land/Bldg/Assessed/Sales), so multi_year_delinquent_tax/two_year_delinquent/
tax_aging_surfaced have no source here -- a genuinely separate research question, not touched by
this module.

Gate off entirely with FORECLOSURE_MACON_ROLLBACK=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

SLUG = "enrichment_macon_rollback_exposure"
STATE, COUNTY = "NC", "Macon"
SERVICE = "https://gis.maconnc.org/arcgis/rest/services/TemplateSite/TaxParcels/MapServer"
LAYER = 0
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_PAGES = int(os.getenv("MACON_ROLLBACK_MAX_PAGES", "10"))
PAGE_SIZE = 2000
ENABLED = os.environ.get("FORECLOSURE_MACON_ROLLBACK") != "0"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _compact_pid(pid: Any) -> str:
    return _NON_ALNUM.sub("", str(pid or "")).upper()


async def fetch_deferred_by_pid(c: httpx.AsyncClient) -> dict[str, dict]:
    """{compact_pid: {"deferred_value", "land_value", "assessed_value"}} from layer 0, positive
    deferrals only."""
    by_pid: dict[str, dict] = {}
    offset = 0
    for _ in range(MAX_PAGES):
        params = {"where": "DEFERMENT > 0", "outFields": "PIN,DEFERMENT,LAND_VALUE,ASSESSED_VALUE",
                  "f": "json", "resultRecordCount": str(PAGE_SIZE), "resultOffset": str(offset)}
        r = await c.get(f"{SERVICE}/{LAYER}/query", params=params)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Macon TaxParcels query error: {data['error']}")
        feats = data.get("features") or []
        for feat in feats:
            attrs = feat.get("attributes", {}) if isinstance(feat, dict) else {}
            pid = _compact_pid(attrs.get("PIN"))
            deferred = attrs.get("DEFERMENT")
            if not pid or not isinstance(deferred, (int, float)) or deferred <= 0:
                continue
            by_pid[pid] = {"deferred_value": float(deferred), "land_value": attrs.get("LAND_VALUE"),
                           "assessed_value": attrs.get("ASSESSED_VALUE")}
        # exceededTransferLimit, not a row-count comparison, is the reliable "more pages exist"
        # signal: the server's own maxRecordCount (which can be smaller than PAGE_SIZE) caps
        # what one response holds regardless of what was asked for -- see
        # scrapers/counties_nc/craven_tax_table.py's own _query_all() for the live-caught bug
        # (Haywood's sibling module) this guards against.
        if not feats or not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return by_pid


def build_rollback_block(rec: dict) -> Optional[dict]:
    deferred = rec.get("deferred_value")
    if not deferred or deferred <= 0:
        return None
    out: dict[str, Any] = {"deferred_value": round(float(deferred), 2),
                           "basis": "present_use_deferral", "county": COUNTY, "state": STATE,
                           "source": "gis.maconnc.org TemplateSite/TaxParcels MapServer "
                                      '("DEFERMENT")',
                           "source_key": SLUG, "rollback_years": ROLLBACK_YEARS_NC,
                           "estimate_is_floor": True, "match_method": "parcel_id"}
    if rec.get("land_value"):
        out["land_value"] = rec["land_value"]
    return out


def _is_macon_nc(li: Listing) -> bool:
    return li.state == STATE and (li.county or "").strip().lower() == COUNTY.lower()


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("rollback_exposure"), dict)


async def enrich_macon_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Fetch Macon's TaxParcels DEFERMENT field ONCE (bulk, paginated), then join locally
    against every Macon NC board row by parcel_id. Writes raw['rollback_exposure'] only when
    DEFERMENT is positive -- never invented."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_MACON_ROLLBACK=0)"}
    targets = [li for li in listings
              if _is_macon_nc(li) and (li.parcel_id or "").strip()
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats = {"eligible": len(targets), "deferred_pids": 0, "matched": 0, "errors": 0}
    if not targets:
        return stats

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA}) as c:
        try:
            by_pid = await fetch_deferred_by_pid(c)
        except Exception:  # noqa: BLE001 - a failed fetch must not crash the run
            stats["errors"] += 1
            log.warning("macon_rollback.fetch_failed")
            return stats
    stats["deferred_pids"] = len(by_pid)

    for li in targets:
        hit = by_pid.get(_compact_pid(li.parcel_id))
        if hit is None:
            continue
        block = build_rollback_block(hit)
        if not block:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rollback_exposure"] = block
        stats["matched"] += 1

    log.info("macon_rollback.done", **stats)
    return stats
