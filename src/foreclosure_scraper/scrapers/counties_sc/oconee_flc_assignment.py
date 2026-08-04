"""Oconee County SC Forfeited Land Commission — the FULL money-trail register.

DISTINCT from the two Oconee sources already wired:
  * ``oconee_tax_sale``       — the annual pre-sale delinquent list (Google Sheet)
  * ``oconee_forfeited_land`` — the ``Assignment_Availability`` FeatureServer,
    which is the map-viewer's *availability* layer: 948 + 76 features, only
    533 distinct TMS, and it carries a single price column per layer
    (``FLC_Price`` / ``FLC_Bid``) with no breakdown.

This module reads the sibling service ``Assignment_FLC`` under the same org
(``UOvRn2Rvzysthh3i``). Same county, same FLC program, but it is the register
of record rather than the map layer, and it publishes the entire cost buildup:

  layer 1  "FLC"         468 rows — Bid, DT_Cost, PriorYr_Tax, Current_Tax,
                         Total_Tax, Abated_Tax, Proc_Fee, FLC_Price, Status,
                         Sale_Date, Year (1999-2019), Comment
  layer 0  "Assignment"  189 rows — FLC_Bid, Redeem_Assign, Date, Comment

Why this lane matters to the operator: an FLC parcel is already county-OWNED.
It was struck off to the Forfeited Land Commission at a past tax sale and no
longer needs to be bid on — it is assignable OVER THE COUNTER at the figure in
``FLC_Price``. That is the buy-direct lane, so the price/status fields are
captured verbatim rather than collapsed into one "opening bid".

Money trail (verified exact on all 468 layer-1 rows, live 2026-08):
    FLC_Price = DT_Cost + Total_Tax + Proc_Fee     <- what you pay to assign
    Bid       = DT_Cost + Total_Tax - Abated_Tax   <- the struck-off bid
``Total_Tax`` is the delinquent TAX itself and is what lands in
``raw[...]['taxes_owed']`` (enrichment_tax_owed's generic scan reads that key);
``FLC_Price`` lands in ``opening_bid`` because that is the actionable number.

Status handling. Layer 1 ``Status`` is one of NONE / SOLD / HOLD; layer 0
``Redeem_Assign`` is NONE / REDEEMED / ASSIGNED / CANCELED / HOLD. Parcels that
have LEFT the inventory (SOLD / REDEEMED / ASSIGNED / CANCELED) are not buyable
and are therefore not emitted as leads — they are counted and logged instead.
Flip ``EMIT_DEPARTED = True`` to emit them anyway (they keep their full money
trail and a precise ``auction_status``).

Dateless: a standing inventory, not a seasonal roster, so no active_months.

Free + compliant: public hosted ArcGIS FeatureServer JSON over plain httpx.
No key, no login, no CAPTCHA/WAF; ``services1.arcgis.com`` serves no robots.txt.
Fields are enumerated explicitly (never ``outFields=*``) and paging uses
``resultOffset``/``resultRecordCount`` with an explicit ``orderByFields`` so the
page window is deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest, raise_for_arcgis_error
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

FS_BASE = ("https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/"
           "Assignment_FLC/FeatureServer")
PAGE_URL = "https://oconeesc.com/auditor-home/forfeited-land"

#: layer 1 = the FLC register (full cost buildup).
FLC_LAYER = 1
#: layer 0 = the assignment register (bid + redeem/assign disposition).
ASSIGNMENT_LAYER = 0

#: Enumerated per-layer field lists. NEVER "*" — we take only the property and
#: money columns we actually use. No personal identifiers exist on this service
#: (no DOB/SSN/DL/phone); ``Owner`` is the record owner of a tax-sale parcel.
FLC_FIELDS = (
    "OBJECTID,TMS,TMS_NUMBER,SUBDIVSION,LOTNUMBER,TMS_ACRES,GIS_ACRES,ID_FLC,"
    "Owner,Description,Year,Bid,DT_Cost,PriorYr_Tax,Current_Tax,Total_Tax,"
    "Abated_Tax,Proc_Fee,FLC_Price,Status,Sale_Date,Comment"
)
ASSIGNMENT_FIELDS = (
    "OBJECTID,TMS,TMS_NUMBER,SUBDIVSION,LOTNUMBER,Acres,GIS_ACRES,ID_ASGN,"
    "Owner,Description,FLC_Bid,Redeem_Assign,Date,Comment"
)

#: ArcGIS caps a page at maxRecordCount (2000 on this service); stay under it.
_PAGE_SIZE = 1000
#: Safety stop — both layers are a few hundred rows.
_MAX_ROWS = 20000

#: Dispositions meaning the parcel has left the buyable FLC inventory.
_DEPARTED = {"SOLD", "REDEEMED", "ASSIGNED", "CANCELED", "CANCELLED"}
#: Set True to emit departed parcels too (money trail + status still captured).
EMIT_DEPARTED = False


def _clean(val: Any) -> str | None:
    """Trim a string attribute; this service pads many cells with a single space."""
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _money(val: Any) -> float | None:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _acres(*vals: Any) -> float | None:
    for v in vals:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


def _epoch_ms_to_dt(val: Any) -> datetime | None:
    """ArcGIS dates are epoch milliseconds UTC; return naive UTC to match the
    rest of the codebase (which uses datetime.utcnow())."""
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


def _centroid(geom: dict[str, Any] | None) -> tuple[float, float] | None:
    """Average of a polygon's ring vertices -> (lat, lng). Geometry is requested
    with outSR=4326, so ring points are [lng, lat]."""
    rings = (geom or {}).get("rings") or []
    pts = [p for ring in rings for p in ring if len(p) >= 2]
    if not pts:
        return None
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lng


def _tms(attrs: dict[str, Any]) -> str | None:
    return _clean(attrs.get("TMS")) or _clean(attrs.get("TMS_NUMBER"))


def tms_key(tms: str | None) -> str:
    """Dedup key: TMS with spaces stripped, uppercased."""
    return (tms or "").upper().replace(" ", "").strip()


def _status_of(attrs: dict[str, Any]) -> str | None:
    """Layer 1 uses Status, layer 0 uses Redeem_Assign."""
    return _clean(attrs.get("Status")) or _clean(attrs.get("Redeem_Assign"))


def is_departed(status: str | None) -> bool:
    """True when the disposition means the parcel is no longer assignable."""
    return (status or "").strip().upper() in _DEPARTED


def _flc_money(attrs: dict[str, Any]) -> dict[str, float | None]:
    """The published cost buildup, verbatim. FLC_Price is the over-the-counter
    assignment price; Total_Tax is the delinquent tax itself."""
    return {
        "bid": _money(attrs.get("Bid")),
        "dt_cost": _money(attrs.get("DT_Cost")),
        "prior_year_tax": _money(attrs.get("PriorYr_Tax")),
        "current_tax": _money(attrs.get("Current_Tax")),
        # Read by enrichment_tax_owed's generic scan -> raw['tax_owed'].
        "taxes_owed": _money(attrs.get("Total_Tax")),
        "abated_tax": _money(attrs.get("Abated_Tax")),
        "processing_fee": _money(attrs.get("Proc_Fee")),
        "flc_price": _money(attrs.get("FLC_Price")),
    }


def _build_listing(
    attrs: dict[str, Any],
    geom: dict[str, Any] | None,
    layer_label: str,
    assignment: dict[str, Any] | None = None,
) -> Listing | None:
    """One parcel -> one Listing. ``assignment`` is the matching layer-0 record
    when the same TMS appears in both registers."""
    tms = _tms(attrs)
    if not tms:
        return None  # without a parcel id the row can't be placed or deduped

    owner = _clean(attrs.get("Owner"))
    desc = _clean(attrs.get("Description"))
    subdiv = _clean(attrs.get("SUBDIVSION"))
    lot = _clean(attrs.get("LOTNUMBER"))
    status = _status_of(attrs)

    if layer_label == "FLC":
        money = _flc_money(attrs)
        # FLC_Price is the actionable number: what the county takes to assign it.
        price = money["flc_price"] or money["bid"]
        sale_date = _epoch_ms_to_dt(attrs.get("Sale_Date"))
        year = attrs.get("Year")
    else:
        money = {"flc_bid": _money(attrs.get("FLC_Bid"))}
        price = money["flc_bid"]
        sale_date = _epoch_ms_to_dt(attrs.get("Date"))
        year = None

    lat = lng = None
    c = _centroid(geom)
    if c:
        lat, lng = c

    assign_status = None
    if assignment:
        assign_status = _status_of(assignment)
        money["assignment_bid"] = _money(assignment.get("FLC_Bid"))

    # auction_status carries the disposition verbatim (lower-cased), so a
    # downstream filter can tell "still assignable" from "gone".
    effective_status = status or assign_status
    bits = [f"Oconee FLC register ({layer_label})"]
    if desc:
        bits.append(desc)
    if subdiv:
        bits.append(subdiv)
    if price:
        bits.append(f"assign price ${price:,.2f}")
    if money.get("taxes_owed"):
        bits.append(f"delinquent tax ${money['taxes_owed']:,.2f}")
    if effective_status:
        bits.append(f"status={effective_status}")

    now = datetime.utcnow()
    return Listing(
        source="counties_sc.oconee_flc_assignment",
        source_url=PAGE_URL,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Oconee",
        parcel_id=tms,
        acreage=_acres(attrs.get("GIS_ACRES"), attrs.get("TMS_ACRES"), attrs.get("Acres")),
        latitude=lat,
        longitude=lng,
        opening_bid=price,
        sale_date=sale_date,
        owner_name=owner,
        defendant=owner,
        auction_status=(effective_status.lower() if effective_status else None),
        legal_description=desc,
        description=" — ".join(bits)[:300],
        foreclosure_process="tax",
        first_seen=now,
        last_seen=now,
        raw={"oconee_flc_assignment": {
            "layer": layer_label,
            "tms": tms,
            "owner": owner,
            "subdivision": subdiv,
            "lot_number": lot,
            # Key must be exactly "year": enrichment_tax_owed's generic scan
            # reads blk.get("year") when it stamps raw['tax_owed'].
            "year": year,
            "status": status,
            "assignment_status": assign_status,
            "assignable": not is_departed(effective_status),
            "sale_date": sale_date.date().isoformat() if sale_date else None,
            "comment": _clean(attrs.get("Comment")),
            "objectid": attrs.get("OBJECTID"),
            **money,
        }},
    )


async def _fetch_layer(c: httpx.AsyncClient, layer: int, fields: str,
                       with_geometry: bool) -> list[dict[str, Any]]:
    """Page a FeatureServer layer. objectIdField is OBJECTID here, but we still
    pass orderByFields so the offset window is deterministic even if the server
    ever reports a null objectIdField."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": fields,
            "returnGeometry": "true" if with_geometry else "false",
            "outSR": "4326",
            "orderByFields": "OBJECTID ASC",
            "resultOffset": str(offset),
            "resultRecordCount": str(_PAGE_SIZE),
            "f": "json",
        }
        url = f"{FS_BASE}/{layer}/query"
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        # ArcGIS answers a token-walled/renamed layer or a bad outFields list
        # with HTTP 200 and {"error": ...} and NO features key, so
        # `data.get("features") or []` would read a dead layer as an empty one.
        # Raise instead — LayerHarvest banks it and verify() fails the run.
        raise_for_arcgis_error(url, data)
        feats = data.get("features") or []
        out.extend(feats)
        if not feats:
            break
        if len(feats) < _PAGE_SIZE and not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
        if offset >= _MAX_ROWS:
            log.warning("oconee_flc_assignment.page_cap", layer=layer, offset=offset)
            break
    return out


def build_listings(flc_feats: list[dict[str, Any]],
                   assign_feats: list[dict[str, Any]]) -> list[Listing]:
    """Merge the two registers into one deduped parcel list.

    A TMS present in both keeps its layer-1 row (the full money trail) and picks
    up the layer-0 disposition; a TMS only in layer 0 is emitted from layer 0.
    """
    assign_by_tms: dict[str, dict[str, Any]] = {}
    for f in assign_feats:
        attrs = dict(f.get("attributes") or {})
        k = tms_key(_tms(attrs))
        if k:
            assign_by_tms.setdefault(k, attrs)

    out: list[Listing] = []
    seen: set[str] = set()
    departed = 0

    for f in flc_feats:
        attrs = dict(f.get("attributes") or {})
        k = tms_key(_tms(attrs))
        if not k or k in seen:
            continue
        li = _build_listing(attrs, f.get("geometry"), "FLC", assign_by_tms.get(k))
        if li is None:
            continue
        seen.add(k)
        if not EMIT_DEPARTED and is_departed(li.auction_status):
            departed += 1
            continue
        out.append(li)

    for f in assign_feats:
        attrs = dict(f.get("attributes") or {})
        k = tms_key(_tms(attrs))
        if not k or k in seen:
            continue
        li = _build_listing(attrs, f.get("geometry"), "Assignment")
        if li is None:
            continue
        seen.add(k)
        if not EMIT_DEPARTED and is_departed(li.auction_status):
            departed += 1
            continue
        out.append(li)

    if departed:
        log.info("oconee_flc_assignment.departed_skipped", count=departed)
    return out


class OconeeFlcAssignment(BaseScraper):
    slug = "counties_sc.oconee_flc_assignment"
    name = "Oconee SC FLC / Assignment Register (full money trail)"
    category = "county_tax"
    expected_min_count = 1  # standing inventory; both layers hold parcels year-round
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        # Both registers are declared up front. Losing either one silently would
        # look like ordinary inventory shrinkage (the FLC roll really does move
        # week to week), so LayerHarvest turns a dead layer into OUTCOME_ERROR
        # instead of a short harvest. Floors are deliberately 0: a county that
        # assigns out its whole inventory is a legitimate empty.
        guard = LayerHarvest(self.slug, ["FLC", "Assignment"])
        async with client(timeout=45.0) as c:
            with guard:
                flc = await guard.harvest(
                    "FLC",
                    lambda: _fetch_layer(c, FLC_LAYER, FLC_FIELDS, with_geometry=True),
                )
                assign = await guard.harvest(
                    "Assignment",
                    lambda: _fetch_layer(c, ASSIGNMENT_LAYER, ASSIGNMENT_FIELDS,
                                         with_geometry=True),
                )
        log.info("oconee_flc_assignment.layers", **guard.stats())
        return build_listings(flc, assign)
