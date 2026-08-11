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

WHY THIS SCRAPER OWNS A COORDINATE (2026-08-11)
-----------------------------------------------
3,262 of this source's 3,309 leads were pinned to the single point
(34.94980, -81.93202) — the Spartanburg city centroid, which on the map is the
ASL "I Love You" sculpture on West Main St. It is the largest coordinate cluster
on the board: 3,390 leads counting the neighbours that share it, out of 15,048
sitting in 71 such clusters.

THE MECHANISM was one parameter. This layer is `esriGeometryPolygon` with real
per-parcel geometry — its own extent is lat 34.8954..34.9891, lon
-82.0029..-81.8378, and every one of the 1,000 features on a test page returns
rings — and the scraper asked for `returnGeometry: "false"`. With no coordinate
of its own, each lead fell through to the geocoder, whose city-level fallback
for "Spartanburg, SC" is that one point (many of these rows have no situs at
all: `PropertyLo` is null on hundreds, and a parcel with no street address can
never geocode to anything better than its city).

The source publishes the coordinate. Spot-checked against the pin, five for
five, the parcels are 2.03-3.48 miles away:
  711264855413 305 WIMBERLY DR    (34.92046,-81.94443)  2.14mi
  712204145906 202 NORTH ST       (34.92038,-81.93344)  2.03mi
  712204052233 239 WOODLAWN AVE   (34.92039,-81.93390)  2.03mi
  713268028103 504 AMELIA AVE     (34.93097,-81.88036)  3.20mi
  710254558929 0 GLADYS CT EXT    (34.92027,-81.98197)  3.48mi

The cost of the pin was never just the map dot. A shared centroid is the input
to the parcel/GIS point query (which then stamps one parcel's assessor row on
everything sharing the point), and it is the origin every comp `distance_mi` is
measured from — so a comp advertised as half a mile away can be two and a half
miles from the house. Fixing it here fixes all three at the source.

When a feature comes back with no usable geometry the lead is left with NO
coordinate and `raw['geo_missing'] = True`, deliberately: an absent coordinate
is handled correctly by every downstream consumer, and a wrong one is not.
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

_PAGE = 1000   # halved once geometry rides along: ~365 KB/page at precision 6

# Spartanburg County, generously bounded. A parcel centroid outside this is a
# projection or datum error, not a location — the layer's own published extent
# is lat 34.8954..34.9891 / lon -82.0029..-81.8378.
_SPBG_LAT = (34.7, 35.3)
_SPBG_LON = (-82.4, -81.6)

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


def parcel_centroid(geom: Any) -> tuple[float, float] | None:
    """(lat, lon) for an esriGeometryPolygon returned in WGS84, or None.

    Area-weighted (shoelace) centroid of the largest ring, so an L-shaped lot
    lands inside its own footprint rather than in the notch. Falls back to the
    vertex mean when the ring is degenerate (zero area — a sliver or a
    duplicated-vertex record), and refuses anything outside Spartanburg County
    rather than publishing a coordinate it cannot vouch for.

    Public so tests can exercise it without touching the network.
    """
    rings = (geom or {}).get("rings") if isinstance(geom, dict) else None
    if not rings:
        return None
    ring = max(rings, key=len)
    pts = [(float(p[0]), float(p[1])) for p in ring
           if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 3:
        return None
    a2 = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cross = x0 * y1 - x1 * y0
        a2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a2) < 1e-12:                       # degenerate ring -> vertex mean
        lon = sum(x for x, _ in pts) / len(pts)
        lat = sum(y for _, y in pts) / len(pts)
    else:
        lon, lat = cx / (3.0 * a2), cy / (3.0 * a2)
    if not (_SPBG_LAT[0] <= lat <= _SPBG_LAT[1] and _SPBG_LON[0] <= lon <= _SPBG_LON[1]):
        return None
    return round(lat, 6), round(lon, 6)


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
                    "where": "1=1", "outFields": _OUT_FIELDS,
                    # The whole point of the docstring block above: this layer
                    # HAS per-parcel geometry, and asking for none is what put
                    # 3,262 leads on one downtown pin. outSR pins WGS84 (the
                    # layer is native Web Mercator) and geometryPrecision caps
                    # the payload at ~365 KB/page.
                    "returnGeometry": "true", "outSR": "4326",
                    "geometryPrecision": "6",
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
                    pt = parcel_centroid(f.get("geometry"))
                    if pt:
                        geo = {"latitude": pt[0], "longitude": pt[1]}
                        geo_raw = {"geo_source": "parcel_polygon_centroid"}
                    else:
                        # No coordinate beats the city centroid. See the
                        # docstring: a shared pin does not just misplace the map
                        # dot, it feeds the parcel point-query and every comp
                        # distance. Flagged so the gap is visible, not guessed.
                        geo = {}
                        geo_raw = {"geo_missing": True}
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
                        **geo,
                        description=(f"Vacant property (Spartanburg City registry) owned by {owner}"
                                     + (" — absentee owner" if absentee else "")),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={
                            **geo_raw,
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
        geo_ok = sum(1 for x in out if x.latitude is not None)
        log.info("spartanburg_vacant.parsed", listings=len(out),
                 with_parcel_coord=geo_ok, no_coord=len(out) - geo_ok)
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = SpartanburgVacant()
        rows = await s.safe_run()
        absentee = sum(1 for x in rows if (x.raw or {}).get("absentee"))
        geo = sum(1 for x in rows if x.latitude is not None)
        coords = {(x.latitude, x.longitude) for x in rows if x.latitude is not None}
        print(f"outcome={s.last_outcome} count={len(rows)} absentee={absentee} "
              f"with_coord={geo} distinct_coords={len(coords)}")
        for li in rows[:10]:
            print(f"  {(li.defendant or '')[:30]:30} situs={(li.street_address or '')[:24]:24} "
                  f"pin={li.parcel_id} @ {li.latitude},{li.longitude}")

    asyncio.run(_main())
