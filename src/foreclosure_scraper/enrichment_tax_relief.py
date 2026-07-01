"""Tax-relief / assessment-status enrichment — senior owner-occupant + rollback-lien.

Two free, property-keyed signals read straight off county parcel layers for leads
already resolved to a parcel:

  * Senior / disabled / blind homestead exemption (NC "elderly or disabled
    exclusion"). Flags a long-tenured senior OWNER-OCCUPANT — the archetype who
    sells on health / downsizing / estate transition, and (unlike an investor)
    usually equity-rich. Buncombe exposes it as Exempt = ELD / DIS / BLD.

  * Present-use / use-value DEFERRAL. In NC, deferred taxes create a ROLLBACK
    LIEN (up to 3 prior years) that comes DUE when the property sells or changes
    use — so a deferral flag is both an equity marker and a transaction-urgency
    signal. Henderson exposes USE_VALUE_DEFERRED / TOTAL_DEFERRED_VALUE.

Enrichment (not a source): tags leads that already carry a parcel_id in a covered
county, by querying that county's parcel layer for the relief field. Reuses the
COUNTY-layer _query + PID-variant helpers. Free, no auth. Adds raw['tax_relief']
and a modest distress-score signal. Gate off with FORECLOSURE_TAX_RELIEF=0.

Extensible: Gaston (LUV_YES_NO / EXEMPT_CODE) and Anderson SC (RATIO=R legal
residence) drop straight into _RELIEF_LAYERS once needed.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
import structlog

from .models import Listing
from .enrichment_owner_mailing import _query, _pid_variants

log = structlog.get_logger()

# (state, county) -> layer config. kind: how to classify a hit.
_RELIEF_LAYERS: dict[tuple[str, str], dict] = {
    ("NC", "Buncombe"): {
        "url": "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/Property_2025/FeatureServer/0",
        "pin_field": "pin",
        "where_extra": "Exempt IN ('ELD','DIS','BLD')",
        "fields": "pin,owner,Exempt",
        "classify": "senior_exemption",
    },
    ("NC", "Henderson"): {
        "url": "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/MapServer/0",
        "pin_field": "PIN",
        "where_extra": "USE_VALUE_DEFERRED > 0",
        "fields": "PIN,PROPERTY_OWNER,TOTAL_DEFERRED_VALUE",
        "classify": "use_value_deferral",
    },
}

_EXEMPT_KIND = {"ELD": "elderly", "DIS": "disabled", "BLD": "blind"}


def _classify(cfg: dict, attrs: dict) -> Optional[dict]:
    if cfg["classify"] == "senior_exemption":
        code = (attrs.get("Exempt") or "").strip().upper()
        kind = _EXEMPT_KIND.get(code)
        if not kind:
            return None
        return {"kind": kind, "basis": "elderly_disabled_exclusion", "code": code}
    if cfg["classify"] == "use_value_deferral":
        val = attrs.get("TOTAL_DEFERRED_VALUE")
        try:
            fv = float(val) if val not in (None, "", " ") else 0.0
        except (TypeError, ValueError):
            fv = 0.0
        if fv <= 0:
            return None
        return {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                "deferred_value": fv}
    return None


async def enrich_tax_relief(listings: list[Listing], max_queries: int = 200) -> dict:
    if os.environ.get("FORECLOSURE_TAX_RELIEF") == "0":
        return {"queried": 0, "tagged": 0}
    targets = [
        li for li in listings
        if li.parcel_id
        and (li.state, (li.county or "").replace(" County", "").strip().title()) in _RELIEF_LAYERS
        and not (li.raw or {}).get("tax_relief")
    ][:max_queries]
    if not targets:
        log.info("tax_relief.no_targets")
        return {"queried": 0, "tagged": 0}

    counts = {"queried": 0, "tagged": 0}
    async with httpx.AsyncClient() as http:
        for li in targets:
            county = (li.county or "").replace(" County", "").strip().title()
            cfg = _RELIEF_LAYERS[(li.state, county)]
            counts["queried"] += 1
            hit = None
            for pid in _pid_variants(li.parcel_id)[:3]:
                safe = pid.replace("'", "''")
                where = f"{cfg['pin_field']} LIKE '%{safe}%' AND {cfg['where_extra']}"
                rows = await _query(http, cfg["url"], where, out_fields=cfg["fields"], count=1)
                if rows:
                    hit = _classify(cfg, rows[0])
                    if hit:
                        break
            if not hit:
                continue
            raw = li.raw if isinstance(li.raw, dict) else {}
            raw["tax_relief"] = {**hit, "county": county}
            li.raw = raw
            counts["tagged"] += 1
    log.info("tax_relief.done", **counts)
    return counts
