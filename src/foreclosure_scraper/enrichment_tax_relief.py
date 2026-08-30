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

MEASURED YIELD, 2026-08-06 — read this before investing more here
    Gaston and Rutherford were added on this date. The parcel joins work
    (Gaston 19/40, Rutherford 39/40 against real board rows), but over a
    600-lead sample of Gaston + Rutherford leads only ONE tagged.

    That is a true base rate, not a bug. Present-use value deferral is a
    FARM/FOREST programme, and this board is residential distress, so the two
    populations barely intersect. The tag is still worth having when it lands
    (the one hit carries a $73,300 rollback lien that comes due on sale), but
    do not expect volume from adding more counties here.

THE ELDERLY EXEMPTION DOES NOT EXTEND BEYOND BUNCOMBE (NC) — checked 2026-08-06
    All 17 NC county parcel layers were probed for an exemption/relief field.
    Seven have one, and on inspection the VALUES are institutional, not
    personal: Rutherford is Religious/Public Service/Charitable/Lodges, Gaston
    is GOV/REL/UTL/CEM, Henderson is Government/Religious/Conservation/Burial.
    Searching every distinct value for elderly/disabled/veteran terms returned
    2 rows in Rutherford, 13 in Gaston ("CAGE" = a charity for the aged, an
    institution rather than a homeowner) and 3 in Henderson.

    York SC publishes HOMESTEAD='Y' (80,620 parcels) — SC's homestead exemption
    for age 65+/disabled/blind — which IS a personal exemption, unlike the NC
    layers above. Also flags FARM USE parcels (5,254) for agricultural rollback.

    Anderson SC RATIO is the 4%/6% assessment class, not a relief flag, and
    Spartanburg HomesteadNumber has 32 non-empty values that look like book
    codes. So the note that once stood here, that Gaston and Anderson SC "drop
    straight in" for senior exemption, was WRONG and is retracted. Buncombe NC
    is unusual in publishing the elderly-or-disabled exclusion per parcel.
    York SC is the SC equivalent for homestead exemption flags.
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
    # 1,576 parcels carry the land-use-value deferral flag, measured 2026-08-06.
    # Gaston stores it as a Y/N string rather than a deferred dollar amount, so
    # there is no value to read, only the flag.
    ("NC", "Gaston"): {
        "url": ("https://gis.gastoncountync.gov/publicgis/rest/services/"
                "PublicGIS/Parcels/FeatureServer/11"),
        # oldPIN, NOT PIN: the board carries undashed 10-digit ids
        # ("3524910792") and this layer's PIN is dashed ("3546-95-5421").
        # oldPIN holds the undashed form and joins 19/40 on real board rows;
        # PIN joins none of them.
        "pin_field": "oldPIN",
        "where_extra": "LUV_YES_NO='Y'",
        "fields": "oldPIN,CURR_NAME1,LUV_YES_NO",
        "classify": "use_value_flag",
    },
    # 2,181 parcels, measured 2026-08-06. THE TRAP: Rutherford types its deferral
    # columns as esriFieldTypeString, so the numeric predicate other counties use
    # ("Use_Value_Deferred > 0") returns ArcGIS error 400 "Unable to complete
    # operation" rather than zero rows. It must be tested as a non-empty STRING.
    # Do not "fix" this to a numeric comparison.
    #
    # Use Use_Value_Deferred, NOT Total_Value_Deferred: the latter is populated
    # on 57,292 rows, i.e. essentially every parcel in the county, because it
    # holds the string "0" for the ones with no deferral.
    ("NC", "Rutherford"): {
        "url": ("https://gis.rutherfordcountync.gov/server/rest/services/"
                "MapMetricsServiceRutherford/MapServer/7"),
        "pin_field": "Parcel_Number",
        "where_extra": "Use_Value_Deferred IS NOT NULL AND Use_Value_Deferred<>''",
        "fields": "Parcel_Number,Property_Owner,Use_Value_Deferred",
        "classify": "use_value_deferral_str",
    },
    # York SC — 80,620 parcels with HOMESTEAD='Y' (SC homestead exemption: age 65+,
    # disabled, or legally blind). This is a KEY lead signal: senior owner-occupants
    # are the archetype who sell on health/downsizing/estate transition. Also flags
    # 5,254 FARM USE parcels (SC agricultural use-value assessment → 3-year rollback
    # on sale per SC Code 12-43-220(d)(4)). Neither field carries a dollar amount,
    # so we report the flag only. ParcelID matches the owner_mailing enricher key.
    ("SC", "York"): {
        "url": ("https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/"
                "Parcels/FeatureServer/0"),
        "pin_field": "ParcelID",
        "where_extra": "HOMESTEAD='Y' OR LandUseDesc LIKE '%FARM%'",
        "fields": "ParcelID,HOMESTEAD,LandUseDesc",
        "classify": "york_sc",
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
    if cfg["classify"] == "use_value_deferral_str":
        # Rutherford types the amount as a string, so parse rather than compare.
        raw = str(attrs.get("Use_Value_Deferred") or "").replace(",", "").strip()
        try:
            fv = float(raw)
        except (TypeError, ValueError):
            fv = 0.0
        if fv <= 0:
            return None
        return {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                "deferred_value": fv}
    if cfg["classify"] == "use_value_flag":
        # Gaston publishes only a Y/N flag, so the rollback lien is known to
        # exist but its size is not published. Report the flag, invent no number.
        if str(attrs.get("LUV_YES_NO") or "").strip().upper() != "Y":
            return None
        return {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                "deferred_value": None}
    if cfg["classify"] == "york_sc":
        # York SC: HOMESTEAD='Y' is the SC homestead exemption (age 65+/disabled/
        # blind). LandUseDesc containing FARM is agricultural use-value assessment
        # (3-year rollback on sale). Neither carries a dollar amount.
        hs = str(attrs.get("HOMESTEAD") or "").strip().upper()
        lu = str(attrs.get("LandUseDesc") or "").strip().upper()
        if hs == "Y":
            return {"kind": "homestead_exemption", "basis": "sc_homestead_age65_disabled",
                    "deferred_value": None}
        if "FARM" in lu:
            return {"kind": "use_value_deferral", "basis": "sc_ag_use_value_rollback",
                    "deferred_value": None}
        return None
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
