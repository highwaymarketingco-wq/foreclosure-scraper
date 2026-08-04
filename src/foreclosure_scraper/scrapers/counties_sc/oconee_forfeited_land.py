"""Oconee County SC Forfeited-Land Commission inventory — ArcGIS FeatureServer.

DISTINCT from ``oconee_tax_sale`` (the annual delinquent-tax SALE list, a
published Google Sheet). This source is the FLC's standing post-sale inventory:
parcels the county struck off to itself at past tax sales and now holds for
over-the-counter purchase or assignment.

oconeesc.com/auditor-home/forfeited-land embeds two ArcGIS Web AppBuilder apps:
  * "available Forfeited Land"      app id 92565e8848cc469cb1c4defa94014ea7
  * "available for Assignment"      app id 9612d2cb97354837bcd934414aecb3a9

Inspecting each app's item ``/data?f=json`` (the Web AppBuilder config) shows
both render the SAME hosted FeatureServer, ``Assignment_Availability`` under org
``UOvRn2Rvzysthh3i``:
  * layer 1 = "FLC"        -> the available-forfeited-land inventory
  * layer 0 = "Assignment" -> parcels available for assignment

Both layers are plain ArcGIS REST FeatureServer query endpoints (free, no key,
no CAPTCHA/WAF) returning polygon features in WGS84 with rich attributes:
TMS, Owner, Description, acreage, FLC bid/price, status, sale date. We query
?where=1=1 with an ENUMERATED outFields list per layer (never "*" — see
_LAYERS), page through with resultOffset (layer 0 holds ~948 features, over the
1000-but-actually-low transfer cap), compute each parcel's polygon centroid for
lat/lng, and emit one Listing per parcel. Losing either layer fails the run
rather than halving the inventory (see layer_guard).

Dateless: this is a standing inventory, not a seasonal sale list, so there is
no active_months window — the layers carry parcels year-round.

Free + compliant: public hosted FeatureServer JSON, plain httpx.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Hosted FeatureServer backing both forfeited-land web apps (see module docstring).
FS_BASE = ("https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/"
           "Assignment_Availability/FeatureServer")
PAGE_URL = "https://oconeesc.com/auditor-home/forfeited-land"

#: (layer id, label, enumerated outFields).
#:
#: The two layers do NOT share a schema — layer 1 carries FLC_Price/Bid/Status/
#: Sale_Date/Year, layer 0 carries Acres/FLC_Bid/Redeem_Assign — so the field
#: list is per layer. Asking either for the other's columns 400s the query.
#:
#: PRIVACY: enumerated, never "*". This used to request "*", which additionally
#: pulled Comment, GlobalID and the whole tax-arithmetic block (DT_Cost,
#: PriorYr_Tax, Current_Tax, Total_Tax, Abated_Tax, Proc_Fee) that nothing here
#: reads. Verified against both layers' ?f=json schemas on 2026-08-04.
_LAYERS: tuple[tuple[int, str, str], ...] = (
    (1, "FLC",
     "OBJECTID,TMS,TMS_NUMBER,Owner,Description,SUBDIVSION,GIS_ACRES,TMS_ACRES,"
     "FLC_Price,Bid,Sale_Date,Status,Year"),
    (0, "Assignment",
     "OBJECTID,TMS,TMS_NUMBER,Owner,Description,SUBDIVSION,GIS_ACRES,TMS_ACRES,"
     "Acres,FLC_Bid,Redeem_Assign"),
)

_PAGE_SIZE = 1000  # ArcGIS hard cap per request; we page with resultOffset.


def _centroid(geom: dict[str, Any]) -> tuple[float, float] | None:
    """Average of a polygon's ring vertices -> (lat, lng). Geometry is already
    WGS84 (outSR=4326), so rings are [lng, lat] pairs."""
    rings = (geom or {}).get("rings") or []
    pts = [p for ring in rings for p in ring if len(p) >= 2]
    if not pts:
        return None
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lng


def _money(val: Any) -> float | None:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _epoch_ms_to_dt(val: Any) -> datetime | None:
    """ArcGIS dates are epoch milliseconds (UTC). Return naive UTC datetime to
    match the rest of the codebase (which uses datetime.utcnow())."""
    try:
        ms = int(val)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _clean(val: Any) -> str | None:
    """Trim a string attribute; ArcGIS pads many cells with a single space."""
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _feature_to_listing(attrs: dict[str, Any], geom: dict[str, Any], label: str) -> Listing | None:
    # TMS is the SC parcel identifier; prefer the longer/cleaner of TMS / TMS_NUMBER.
    tms = _clean(attrs.get("TMS")) or _clean(attrs.get("TMS_NUMBER"))
    if not tms:
        return None  # without a parcel id the row can't be placed or deduped

    owner = _clean(attrs.get("Owner"))
    desc = _clean(attrs.get("Description"))
    subdiv = _clean(attrs.get("SUBDIVSION"))

    acreage = None
    for fld in ("GIS_ACRES", "TMS_ACRES", "Acres"):
        a = attrs.get(fld)
        try:
            af = float(a)
        except (TypeError, ValueError):
            continue
        if af > 0:
            acreage = af
            break

    # Layer 1 (FLC) -> FLC_Price/Bid; layer 0 (Assignment) -> FLC_Bid.
    opening_bid = (_money(attrs.get("FLC_Price")) or _money(attrs.get("Bid"))
                   or _money(attrs.get("FLC_Bid")))

    sale_date = _epoch_ms_to_dt(attrs.get("Sale_Date"))
    status = _clean(attrs.get("Status")) or _clean(attrs.get("Redeem_Assign"))

    lat = lng = None
    c = _centroid(geom)
    if c:
        lat, lng = c

    desc_bits = [f"Oconee FLC ({label})"]
    if desc:
        desc_bits.append(desc)
    if subdiv:
        desc_bits.append(subdiv)
    if status:
        desc_bits.append(f"status={status}")
    description = " — ".join(desc_bits)

    return Listing(
        source="counties_sc.oconee_forfeited_land",
        source_url=PAGE_URL,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Oconee",
        parcel_id=tms,
        acreage=acreage,
        latitude=lat,
        longitude=lng,
        opening_bid=opening_bid,
        sale_date=sale_date,
        defendant=owner,
        owner_name=owner,
        auction_status=(status.lower() if status else None),
        legal_description=desc,
        description=description,
        foreclosure_process="tax",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"oconee_forfeited_land": {
            "layer": label,
            "tms": tms,
            "owner": owner,
            "status": status,
            "fll_bid": opening_bid,
            "year": attrs.get("Year"),
            "objectid": attrs.get("OBJECTID"),
        }},
    )


async def _fetch_layer(c: httpx.AsyncClient, layer: int, label: str,
                       out_fields: str) -> list[Listing]:
    """One layer -> Listings. RAISES on failure.

    The hand-rolled paginator this replaces logged
    ``oconee_forfeited_land.arcgis_error`` and ``break``-ed on an
    HTTP-200-with-error-body, returning whatever it had already collected — so
    a dead or renamed layer looked like a layer with no parcels in it.
    ``query_features`` owns the paging, the error-body check, the
    repeated-OBJECTID guard and the ban on ``outFields='*'``; ``LayerHarvest``
    in :meth:`OconeeForfeitedLand.fetch` turns a lost layer into a run ERROR.
    """
    feats = await agw.query_features(
        c, f"{FS_BASE}/{layer}", where="1=1", out_fields=out_fields,
        return_geometry=True, out_sr=4326, page=_PAGE_SIZE, max_records=20000)
    out: list[Listing] = []
    for f in feats:
        li = _feature_to_listing(
            dict(f.get("attributes") or {}), f.get("geometry") or {}, label
        )
        if li is not None:
            out.append(li)
    return out


class OconeeForfeitedLand(BaseScraper):
    slug = "counties_sc.oconee_forfeited_land"
    name = "Oconee SC Forfeited Land Commission (ArcGIS FeatureServer)"
    category = "county_tax"
    expected_min_count = 1  # standing inventory; both layers currently hold parcels
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        # Both layers are declared: losing one has to fail the run rather than
        # halve the inventory, because half the FLC roll is a believable number.
        guard = LayerHarvest(self.slug, [label for _id, label, _f in _LAYERS])
        with guard:
            async with client(timeout=45.0) as c:
                for layer, label, fields in _LAYERS:
                    rows = await guard.harvest(
                        label,
                        lambda ly=layer, lb=label, fl=fields: _fetch_layer(c, ly, lb, fl))
                    for li in rows:
                        # Dedupe across the two layers (a parcel can sit in both
                        # the FLC inventory and the assignment list) on parcel id.
                        key = (li.parcel_id or "").upper().replace(" ", "")
                        if key and key in seen:
                            continue
                        if key:
                            seen.add(key)
                        out.append(li)
        return out
