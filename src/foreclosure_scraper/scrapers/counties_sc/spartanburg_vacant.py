"""Spartanburg City vacant-property registry — absentee + vacant motivated sellers.

The City of Spartanburg publishes its full vacant-parcel roll as a free, public
ArcGIS layer ("allvacant", 5,014 parcels, no login). Each row carries the owner,
the owner's MAILING address (usually a PO box or out-of-county address — the
absentee flag is baked in), the situs, the TMS/PIN, and CAMA specs (year built,
condition, living area, beds/baths). A vacant parcel whose owner mails from
elsewhere is a classic motivated seller: a non-performing, deteriorating asset
the owner has already physically left.

Free + compliant: public ArcGIS REST, no login/CAPTCHA/pay. Government owners
(city/county/state/housing authority) are dropped — they are not sellers.
Dateless standing inventory -> DATELESS_OK_SOURCES; refresh each run.

Bonus: the CAMA specs (living_sqft/year_built/beds/baths/condition) ride along
in raw so downstream ARV/vision can use them without a second lookup.
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

LAYER = ("https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
         "City_Owned_and_Vacant_Properties/FeatureServer/0/query")

_OUT_FIELDS = ",".join([
    "TAXPIN", "OwnerName", "TaxpayerNa", "StreetAddr", "City", "State", "Zip",
    "PropertyLo", "SaleDate", "SaleAmount", "YearBuilt", "ConditionF",
    "LivingArea", "BedRooms", "FullBaths", "HalfBaths", "LandUse", "PropertyTy",
])

_PAGE = 2000

# Owners that are governments / authorities — not motivated sellers.
_GOV = re.compile(
    r"\b(CITY OF|COUNTY OF|STATE OF|SPARTANBURG COUNTY|HOUSING AUTHORITY|"
    r"REDEVELOPMENT|SCHOOL DISTRICT|UNITED STATES|SECRETARY OF|DEPARTMENT OF|"
    r"COMMISSIONERS OF PUBLIC WORKS|SC DEPARTMENT|MUNICIPAL)\b", re.I)

# ConditionF codes that flag genuinely deteriorated structures (extra distress).
_POOR_COND = {"PR", "P", "VP", "UN", "UNSOUND", "POOR", "VERY POOR"}


def _clean(v: Any) -> str | None:
    if v in (None, "", " ", 0, "0"):
        return None
    return re.sub(r"\s+", " ", str(v)).strip() or None


def _mailing(a: dict) -> str | None:
    parts = [a.get("StreetAddr"), a.get("City"), a.get("State"), a.get("Zip")]
    out = " ".join(str(p).strip() for p in parts if p not in (None, "", " "))
    return re.sub(r"\s+", " ", out).strip() or None


def _is_absentee(a: dict) -> bool:
    """Owner mails from outside Spartanburg / SC, or from a PO box."""
    city = (a.get("City") or "").strip().upper()
    state = (a.get("State") or "").strip().upper()
    street = (a.get("StreetAddr") or "").strip().upper()
    if state and state != "SC":
        return True
    if "PO BOX" in street or "P O BOX" in street or "P.O." in street:
        return True
    if city and city not in ("SPARTANBURG", "ROEBUCK", ""):
        return True
    return False


def _kind(a: dict) -> PropertyKind:
    situs = (a.get("PropertyLo") or "").strip()
    try:
        liv = float(a.get("LivingArea") or 0)
    except (TypeError, ValueError):
        liv = 0
    try:
        yr = int(float(a.get("YearBuilt") or 0))
    except (TypeError, ValueError):
        yr = 0
    if situs.startswith("0 ") or (liv <= 0 and yr <= 0):
        return PropertyKind.LAND
    return PropertyKind.SINGLE_FAMILY


class SpartanburgVacant(BaseScraper):
    slug = "counties_sc.spartanburg_vacant"
    name = "Spartanburg City Vacant Properties (absentee + vacant)"
    category = "motivated_seller"
    expected_min_count = 50
    timeout_s = 180.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=40.0) as c:
            offset = 0
            while True:
                params = {
                    "where": "1=1", "outFields": _OUT_FIELDS, "returnGeometry": "false",
                    "resultOffset": str(offset), "resultRecordCount": str(_PAGE), "f": "json",
                }
                try:
                    r = await c.get(LAYER, params=params)
                    feats = (r.json() or {}).get("features") or []
                except Exception as exc:  # noqa: BLE001
                    log.warning("spartanburg_vacant.page_fail", offset=offset, error=str(exc)[:120])
                    break
                if not feats:
                    break
                for f in feats:
                    a = f.get("attributes") or {}
                    owner = _clean(a.get("OwnerName"))
                    if not owner or _GOV.search(owner):
                        continue
                    situs = _clean(a.get("PropertyLo"))
                    parcel = _clean(a.get("TAXPIN"))
                    if not (situs or parcel):
                        continue
                    absentee = _is_absentee(a)
                    cond = (a.get("ConditionF") or "").strip().upper()
                    poor = cond in _POOR_COND
                    li = Listing(
                        source=self.slug,
                        source_url=("https://services9.arcgis.com/HoRra3ATPLGmyjn6/"
                                    "arcgis/rest/services/City_Owned_and_Vacant_Properties/FeatureServer/0"),
                        listing_type=ListingType.UNKNOWN,
                        property_kind=_kind(a),
                        state="SC",
                        county="Spartanburg",
                        city="Spartanburg",
                        street_address=situs,
                        parcel_id=parcel,
                        defendant=owner,
                        sale_date=None,
                        description=(f"Vacant property (Spartanburg City registry) owned by {owner}"
                                     + (" — absentee owner" if absentee else "")),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={
                            "vacant": {"source": "spartanburg_city_registry", "condition": cond or None},
                            # scores via distress_score PROPERTY "distressed_condition" (w=8)
                            "distressed": True,
                            "owner_mailing": _mailing(a),
                            "absentee": absentee,
                            **({"code_enforcement": True} if poor else {}),
                            "cama_specs": {
                                k: a.get(v) for k, v in (
                                    ("living_sqft", "LivingArea"), ("year_built", "YearBuilt"),
                                    ("bedrooms", "BedRooms"), ("full_baths", "FullBaths"),
                                    ("condition", "ConditionF"), ("land_use", "LandUse"),
                                ) if a.get(v) not in (None, "", 0, "0")
                            },
                        },
                    )
                    out.append(li)
                if len(feats) < _PAGE:
                    break
                offset += _PAGE
        log.info("spartanburg_vacant.parsed", listings=len(out))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = SpartanburgVacant()
        rows = await s.safe_run()
        absentee = sum(1 for x in rows if (x.raw or {}).get("absentee"))
        print(f"outcome={s.last_outcome} count={len(rows)} absentee={absentee}")
        for li in rows[:10]:
            print(f"  {(li.defendant or '')[:34]:34} situs={(li.street_address or '')[:28]:28} "
                  f"abs={(li.raw or {}).get('absentee')} pin={li.parcel_id}")

    asyncio.run(_main())
