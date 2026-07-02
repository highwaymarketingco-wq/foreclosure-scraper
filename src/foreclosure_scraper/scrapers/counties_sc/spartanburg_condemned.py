"""Spartanburg County condemned / dilapidated structures — a direct-condemnation
distress SIGNAL keyed to the parcel.

WHY NOT the county's dedicated "Condemned_Properties" service:
    maps.spartanburgcounty.org/server/rest/services/GIS/Condemned_Properties/MapServer
    (mapName "Condemned Residential", documentInfo keyword "condemned") is a
    LIVE-BUT-EMPTY SHELL as of 2026-07-02: it enumerates 0 layers (`/0` -> HTTP
    404 "Layer not found", `/layers` -> []), `find`/`identify` return `[]`, and
    `export` renders a blank tile. The enumeration technique is sound — sibling
    services on the SAME server (County_Line, Assessed_Land_Use) enumerate their
    layers fine — the county simply stripped/broke the operational layers while
    leaving the service published. There is no queryable condemned data behind it.
    (EnerGov spatial collections are generic Point/Line/Polygon buckets, and
    CAMA.PermitType is null across the dataset — both dead ends for this signal.)

WHAT WE USE INSTEAD (compliant, live, net-new):
    The county CAMA_Parcels FeatureServer carries a per-structure condition code.
    ConditionFactor='DL' / CDUC='DELAPITATED' is the assessor's own dilapidated /
    uninhabitable tier — 681 distinct parcels (live-verified 2026-07-02). This is
    the closest queryable proxy for a condemned structure Spartanburg exposes for
    free, and dilapidation is itself a first-class distress signal (a structure
    the assessor rates unlivable is a classic motivated-seller / tear-down lead).

    Free + compliant: open ArcGIS REST FeatureServer query, no login/CAPTCHA/pay.

EMISSION MODEL (per the parcel-keyed backbone):
    Each row is emitted as a Listing keyed on the parcel (dedupe key
    parcel:{state}:{county}:{pin} — GISParcelNumber '7103-72-1872.64' normalizes
    to the same 12-digit key as the City registry's compact TAXPIN '710372187264',
    so these MERGE cleanly). raw['condemned'] is set, which distress_score reads as
    the PROPERTY "code_enforcement" signal (w=14). If the parcel already exists on
    the board from another source, Listing.merge() deep-merges raw and the condemned
    flag rides onto that existing lead; if net-new, it stands as its own Listing.

    Bonus: owner mailing + CAMA specs (year/living area/beds/baths/values) ride in
    raw so downstream skip-trace / ARV / vision reuse them without a second lookup.

Government / utility owners are dropped (not sellers). Dateless standing
inventory -> DATELESS_OK_SOURCES; refresh each run.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

LAYER = ("https://maps.spartanburgcounty.org/server/rest/services/"
         "GIS/CAMA_Parcels/FeatureServer/0/query")
SERVICE_URL = ("https://maps.spartanburgcounty.org/server/rest/services/"
               "GIS/CAMA_Parcels/FeatureServer/0")

# The assessor condition tiers that denote a genuinely condemned / uninhabitable
# structure. 'DL' (DELAPITATED) is the strong, condemned-equivalent tier; 'VP'
# (VERY POOR) is a weaker deterioration tier carried as secondary context.
_CONDEMNED_COND = "DL"           # -> raw['condemned'] (code_enforcement, w=14)
_POOR_COND = "VP"                # -> raw['distressed'] only (distressed_condition, w=8)
_WHERE = "ConditionFactor IN ('DL','VP')"

_OUT_FIELDS = ",".join([
    "GISParcelNumber", "MAPNUMBER", "PARCELNUMBER", "OwnerName", "TaxpayerName",
    "PropertyLocation", "StreetAddress", "City", "State", "Zip",
    "YearBuilt", "LivingArea", "BedRooms", "FullBaths", "HalfBaths",
    "ConditionFactor", "CDUC", "PropertyType", "BuildingType", "LandUse",
    "CurrentAppraisedBuildingValue", "CurrentAppraisedLandValue",
    "CurrentTaxableBuildingValue", "CurrentTaxableLandValue",
])

_PAGE = 2000  # matches the service maxRecordCount

# Owners that are governments / authorities / utilities — not motivated sellers.
_GOV = re.compile(
    r"\b(CITY OF|COUNTY OF|STATE OF|SPARTANBURG COUNTY|HOUSING AUTHORITY|"
    r"REDEVELOPMENT|SCHOOL DISTRICT|UNITED STATES|SECRETARY OF|DEPARTMENT OF|"
    r"COMMISSIONERS OF PUBLIC WORKS|SC DEPARTMENT|MUNICIPAL|WATER (DISTRICT|SYSTEM)|"
    r"SEWER|SANITARY|ELECTRIC (CITY|COOP)|DUKE ENERGY|UTILITIES)\b", re.I)


def _clean(v: Any) -> str | None:
    if v in (None, "", " ", 0, "0"):
        return None
    return re.sub(r"\s+", " ", str(v)).strip() or None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _int(v: Any) -> int | None:
    try:
        i = int(float(v))
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


def _mailing(a: dict) -> str | None:
    parts = [a.get("StreetAddress"), a.get("City"), a.get("State"), a.get("Zip")]
    out = " ".join(str(p).strip() for p in parts if p not in (None, "", " "))
    return re.sub(r"\s+", " ", out).strip() or None


def _is_absentee(a: dict) -> bool:
    """Owner mails from outside Spartanburg County / SC, or from a PO box."""
    city = (a.get("City") or "").strip().upper()
    state = (a.get("State") or "").strip().upper()
    street = (a.get("StreetAddress") or "").strip().upper()
    if state and state != "SC":
        return True
    if "PO BOX" in street or "P O BOX" in street or "P.O." in street:
        return True
    # Situs is always in-county; if the mailing city is a clearly-different metro
    # it's an absentee owner. Keep the local Spartanburg-metro towns as resident.
    _local = {
        "SPARTANBURG", "ROEBUCK", "INMAN", "GREER", "DUNCAN", "LYMAN", "WELLFORD",
        "MOORE", "WOODRUFF", "CHESNEE", "PACOLET", "CAMPOBELLO", "COWPENS",
        "ENOREE", "GRAMLING", "LANDRUM", "STARTEX", "REIDVILLE", "CONVERSE", "",
    }
    if city and city not in _local:
        return True
    return False


def _kind(a: dict) -> PropertyKind:
    situs = (a.get("PropertyLocation") or "").strip()
    liv = _num(a.get("LivingArea")) or 0
    yr = _int(a.get("YearBuilt")) or 0
    ptype = (a.get("PropertyType") or "").upper()
    if "COM" in ptype:
        return PropertyKind.COMMERCIAL
    if situs.startswith("0 ") or (liv <= 0 and yr <= 0):
        return PropertyKind.LAND
    return PropertyKind.SINGLE_FAMILY


def _parcel(a: dict) -> str | None:
    # GISParcelNumber is the dashed TMS-style PIN ('7103-72-1872.64'); it
    # normalizes to the same dedupe key as the compact 12-digit county PIN used
    # by other Spartanburg sources. MAPNUMBER is a distant fallback.
    return _clean(a.get("GISParcelNumber")) or _clean(a.get("MAPNUMBER"))


def _appraised_total(a: dict) -> float | None:
    b = _num(a.get("CurrentAppraisedBuildingValue")) or 0
    land = _num(a.get("CurrentAppraisedLandValue")) or 0
    tot = b + land
    return tot or None


class SpartanburgCondemned(BaseScraper):
    slug = "counties_sc.spartanburg_condemned"
    name = "Spartanburg County Condemned / Dilapidated Structures"
    category = "motivated_seller"
    expected_min_count = 200          # ~681 dilapidated + very-poor is ~1,842 total
    timeout_s = 180.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_keys: set[str] = set()
        async with client(timeout=45.0) as c:
            offset = 0
            while True:
                params = {
                    "where": _WHERE,
                    "outFields": _OUT_FIELDS,
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultOffset": str(offset),
                    "resultRecordCount": str(_PAGE),
                    "orderByFields": "OBJECTID",
                    "f": "json",
                }
                try:
                    r = await c.get(LAYER, params=params)
                    body = r.json() or {}
                except Exception as exc:  # noqa: BLE001
                    log.warning("spartanburg_condemned.page_fail",
                                offset=offset, error=str(exc)[:120])
                    break
                if body.get("error"):
                    log.warning("spartanburg_condemned.api_error",
                                offset=offset, error=str(body.get("error"))[:160])
                    break
                feats = body.get("features") or []
                if not feats:
                    break
                for f in feats:
                    li = self._to_listing(f)
                    if li is None:
                        continue
                    # De-dupe multi-card rows within this run (same parcel, many
                    # building cards) so we emit one condemned lead per parcel.
                    key = li.parcel_id or (li.street_address or "")
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    out.append(li)
                if len(feats) < _PAGE:
                    break
                offset += _PAGE
        log.info("spartanburg_condemned.parsed", listings=len(out))
        return out

    def _to_listing(self, f: dict) -> Listing | None:
        a = f.get("attributes") or {}
        owner = _clean(a.get("OwnerName"))
        if not owner or _GOV.search(owner):
            return None
        situs = _clean(a.get("PropertyLocation"))
        parcel = _parcel(a)
        if not (situs or parcel):
            return None

        cond = (a.get("ConditionFactor") or "").strip().upper()
        cduc = _clean(a.get("CDUC"))
        condemned = cond == _CONDEMNED_COND      # DL / DELAPITATED
        absentee = _is_absentee(a)

        # geometry: polygon centroid-ish (first ring vertex) or a point
        lat = lon = None
        g = f.get("geometry") or {}
        if "x" in g and "y" in g:
            lon, lat = g.get("x"), g.get("y")
        elif g.get("rings"):
            try:
                pt = g["rings"][0][0]
                lon, lat = pt[0], pt[1]
            except (IndexError, TypeError):
                pass

        specs = {
            k: v for k, v in (
                ("living_sqft", _num(a.get("LivingArea"))),
                ("year_built", _int(a.get("YearBuilt"))),
                ("bedrooms", _int(a.get("BedRooms"))),
                ("full_baths", _int(a.get("FullBaths"))),
                ("half_baths", _int(a.get("HalfBaths"))),
                ("condition", cduc),
                ("land_use", _clean(a.get("LandUse"))),
                ("building_type", _clean(a.get("BuildingType"))),
            ) if v not in (None, "", 0)
        }

        tier = "condemned" if condemned else "very_poor"
        desc = (f"{'Condemned/dilapidated' if condemned else 'Very-poor-condition'} "
                f"structure (Spartanburg assessor CDUC={cduc or cond}) owned by {owner}"
                + (" — absentee owner" if absentee else ""))

        raw: dict[str, Any] = {
            "condemned_signal": {
                "source": "spartanburg_cama_condition",
                "condition_code": cond or None,
                "condition_label": cduc,
                "tier": tier,
            },
            "distressed": True,                 # distressed_condition (w=8)
            "owner_mailing": _mailing(a),
            "absentee": absentee,
            "cama_specs": specs or None,
        }
        if condemned:
            # The signal distress_score keys on: raw['condemned'] -> code_enforcement (w=14)
            raw["condemned"] = True
            raw["code_enforcement"] = True

        appraised = _appraised_total(a)

        return Listing(
            source=self.slug,
            source_url=SERVICE_URL,
            listing_type=ListingType.UNKNOWN,
            property_kind=_kind(a),
            state="SC",
            county="Spartanburg",
            street_address=situs,
            zip_code=(_clean(a.get("Zip")) or None),
            parcel_id=parcel,
            latitude=lat,
            longitude=lon,
            defendant=owner,
            owner_name=owner,
            year_built=_int(a.get("YearBuilt")),
            living_sqft=_num(a.get("LivingArea")),
            market_value=appraised,
            sale_date=None,
            description=desc,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={k: v for k, v in raw.items() if v not in (None, {}, [])},
        )


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = SpartanburgCondemned()
        rows = await s.safe_run()
        condemned = sum(1 for x in rows if (x.raw or {}).get("condemned"))
        absentee = sum(1 for x in rows if (x.raw or {}).get("absentee"))
        print(f"outcome={s.last_outcome} count={len(rows)} "
              f"condemned={condemned} very_poor={len(rows) - condemned} absentee={absentee}")
        for li in rows[:10]:
            sig = (li.raw or {}).get("condemned_signal") or {}
            print(f"  {(li.defendant or '')[:30]:30} situs={(li.street_address or '')[:26]:26} "
                  f"pin={li.parcel_id} tier={sig.get('tier')} "
                  f"condemned={(li.raw or {}).get('condemned', False)}")

    asyncio.run(_main())
