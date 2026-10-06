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

2026-10-02 BREADTH FIX — a use_value_deferral hit ALSO stamps raw['rollback_exposure'].
    `enrichment_rollback_deferral.py` (the OTHER module that models this exact
    "rollback tax comes due on sale" liability, Buncombe + Anderson only) and the
    county-signal coverage tracker both read `raw['rollback_exposure']`
    specifically — not `raw['tax_relief']`. So Henderson/Gaston/Rutherford/York's
    real, live use_value_deferral hits (confirmed live 2026-10-02: Henderson 1,598
    parcels, Rutherford 1,917, Gaston+York as already documented above) were never
    counted there at all, even though the distress-score signal itself
    (`deferral_rollback`, FINANCIAL w=6) already fires correctly off raw['tax_relief'].
    This was a raw-key naming gap, the same shape as the `lincoln_code`-vs-
    `code_enforcement` gap found the same day — not a missing source. Fixed by also
    writing raw['rollback_exposure'] in the same shape enrichment_rollback_deferral.py
    uses, with NO invented tax rate (these counties' parcel layers carry a deferred
    VALUE but no per-parcel tax-bill amount, unlike Buncombe's bills layer) —
    `annual_deferred_tax`/`estimated_rollback` stay None with `tax_rate_source`
    explaining why, exactly the same "report the real number, never guess a millage"
    discipline this file already applies to Gaston's flag-only LUV_YES_NO. Only
    fires for kind=="use_value_deferral" (never senior/disabled/homestead hits,
    which are not a rollback liability).

    Burke NC (2026-10-02 addition, live-verified: 1,560 real parcels with
    TOTAL_DEFERRED_VALUE>0) carries the IDENTICAL schema as Henderson (same
    LAND_USE_VALUE/USE_VALUE_DEFERRED/HISTORIC_VALUE_DEFERRED/TOTAL_DEFERRED_VALUE
    field names — same regional CAMA vendor), so it reuses Henderson's exact
    classify path.

    Lincoln NC (2026-10-02 addition, live-verified against the COUNTY PARCEL layer,
    a different endpoint than the dedicated lincoln_code_violations.py scraper's
    TRACKiT code-case layer): `LANDEFERRED` is NOT a dollar amount -- sampled live
    rows all read exactly -1, confirming it is a boolean flag encoded the old
    FoxPro/dBase way (TRUE=-1), not a value field. Reported as a flag-only hit
    (deferred_value=None), the same honest treatment Gaston's Y/N LUV_YES_NO
    already gets here -- do NOT "fix" this to read LANDEFERRED as a dollar figure.

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

from . import condo_units
from .models import Listing
from .enrichment_owner_mailing import _query, _pid_variants

log = structlog.get_logger()

# Statutory rollback lookback in tax years, by state -- same constant
# enrichment_rollback_deferral.py defines (NC G.S. 105-277.4(c): current year +
# 3 preceding; SC Code 12-43-220(d)(4): 3 preceding). Duplicated rather than
# imported to avoid a cross-module dependency for one dict literal.
_ROLLBACK_YEARS = {"NC": 4, "SC": 3}

# (state, county) -> layer config. kind: how to classify a hit.
_RELIEF_LAYERS: dict[tuple[str, str], dict] = {
    ("NC", "Buncombe"): {
        "url": "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/Property_2025/FeatureServer/0",
        "pin_field": "pin",
        # A condominium unit's parcel_id is its own pinnum ('9627023924C0102', condo_units.py) and
        # `pin` is the building's 10 digits: a unit is matched on `pinnum`, a plain parcel on `pin`.
        # Live 2026-10-06 (Property_2025/FeatureServer/0?f=json): pinnum esriFieldTypeString(15).
        "unit_field": "pinnum",
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
    # Burke NC (2026-10-02 county-breadth pass, docs: rollback_exposure investigation).
    # IDENTICAL schema to Henderson -- same field names (LAND_USE_VALUE/
    # USE_VALUE_DEFERRED/HISTORIC_VALUE_DEFERRED/TOTAL_DEFERRED_VALUE), same
    # regional CAMA vendor. Live-verified 2026-10-02: 1,560 real parcels with
    # TOTAL_DEFERRED_VALUE>0 (1,548 via USE_VALUE_DEFERRED>0 -- both numeric fields,
    # unlike Rutherford's string-typed pair), real dollar amounts sampled
    # (e.g. $225,888, $100,645, $18,752), reuses Henderson's exact classify path.
    ("NC", "Burke"): {
        "url": "https://gis.burkenc.org/arcgis/rest/services/ProdParcelViewFC/MapServer/0",
        "pin_field": "PIN",
        "where_extra": "USE_VALUE_DEFERRED > 0",
        "fields": "PIN,PROPERTY_OWNER,TOTAL_DEFERRED_VALUE",
        "classify": "use_value_deferral",
    },
    # Lincoln NC (2026-10-02 addition). This is the COUNTY PARCEL layer (a
    # different endpoint than counties_nc.lincoln_code_violations.py's own
    # TRACKiT code-case layer on the same host). LANDEFERRED is NOT a dollar
    # amount -- live-sampled rows (PINs 2646891349, 2647803354, 2654968268, ...)
    # all read exactly -1, the old FoxPro/dBase boolean-TRUE convention, not a
    # value. 2,444 real parcels carry a non-zero (i.e. -1/"flagged") value,
    # live-verified 2026-10-02. Reported flag-only, same honest treatment as
    # Gaston's LUV_YES_NO below -- never invent a dollar figure from a flag.
    ("NC", "Lincoln"): {
        "url": ("https://arcgisserver.lincolncountync.gov/arcgis/rest/services/"
                "Server_TaxParcelViewerSP/MapServer/0"),
        "pin_field": "PIN",
        "where_extra": "LANDEFERRED <> 0 AND LANDEFERRED IS NOT NULL",
        "fields": "PIN,NAME1,LANDEFERRED",
        "classify": "lincoln_use_value_flag",
        # arcgisserver.lincolncountync.gov serves an incomplete TLS chain (same
        # server-side misconfiguration counties_nc.lincoln_code_violations.py
        # already works around) -- httpx's default verify=True fails with
        # "unable to get local issuer certificate" against this exact host.
        "insecure_tls": True,
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
    if cfg["classify"] == "lincoln_use_value_flag":
        # Lincoln's LANDEFERRED is a boolean flag (-1 = true, old FoxPro/dBase
        # convention), NOT a dollar amount -- live-verified 2026-10-02, every
        # sampled nonzero row read exactly -1. Report the flag, invent no number,
        # same discipline as Gaston's LUV_YES_NO above.
        val = attrs.get("LANDEFERRED")
        try:
            fv = float(val) if val not in (None, "", " ") else 0.0
        except (TypeError, ValueError):
            fv = 0.0
        if fv == 0:
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
    # Lincoln's host serves an incomplete TLS chain (see _RELIEF_LAYERS note) --
    # a SEPARATE client scoped to only that one config's queries, never a change
    # to the shared client every other county's query runs through.
    async with httpx.AsyncClient() as http, httpx.AsyncClient(verify=False) as http_insecure:
        for li in targets:
            county = (li.county or "").replace(" County", "").strip().title()
            cfg = _RELIEF_LAYERS[(li.state, county)]
            use_http = http_insecure if cfg.get("insecure_tls") else http
            counts["queried"] += 1
            hit = None
            unit = cfg.get("unit_field") and condo_units.unit_pinnum(li.state, county, li.parcel_id)
            pin_field, pids = ((cfg["unit_field"], [unit]) if unit
                               else (cfg["pin_field"], _pid_variants(li.parcel_id)[:3]))
            for pid in pids:
                safe = pid.replace("'", "''")
                where = f"{pin_field} LIKE '%{safe}%' AND {cfg['where_extra']}"
                rows = await _query(use_http, cfg["url"], where, out_fields=cfg["fields"], count=1)
                if rows:
                    hit = _classify(cfg, rows[0])
                    if hit:
                        break
            if not hit:
                continue
            raw = li.raw if isinstance(li.raw, dict) else {}
            raw["tax_relief"] = {**hit, "county": county}
            # 2026-10-02 breadth fix: also promote a rollback-liability hit into
            # raw['rollback_exposure'], the key enrichment_rollback_deferral.py and
            # the county-signal coverage tracker actually read -- see module
            # docstring. Never for senior/disabled/homestead kinds (not a rollback).
            if hit["kind"] == "use_value_deferral":
                raw["rollback_exposure"] = {
                    "deferred_value": hit.get("deferred_value"),
                    "rollback_years": _ROLLBACK_YEARS.get(li.state),
                    "annual_deferred_tax": None,
                    "estimated_rollback": None,
                    "estimate_is_floor": None,
                    "tax_rate_source": "unavailable_no_bill_layer",
                    "basis": hit["basis"],
                    "county": county,
                    "state": li.state,
                    "source": f"{county} County parcel layer (tax_relief.{cfg['classify']})",
                    "source_key": f"tax_relief_{county.lower()}",
                    "match_method": "parcel",
                }
            li.raw = raw
            counts["tagged"] += 1
    log.info("tax_relief.done", **counts)
    return counts
