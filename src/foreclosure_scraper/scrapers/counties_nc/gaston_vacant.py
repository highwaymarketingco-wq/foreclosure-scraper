"""Gaston County NC vacant parcels — a PROPERTY-KEYED motivated-seller / distress source.

The county public parcel GIS carries a per-parcel `VacantImpro` flag. `VacantImpro='Vacant'`
means the parcel has NO improvements (vacant lot / unbuilt land). Vacant land is a classic
distress / absentee signal: holding costs with no rental income, often owned out-of-county
(the mailing address `CURR_*` frequently differs from the situs), and owners are commonly
motivated to offload. Unlike a name-indexed lane this is property-keyed: ONE bulk query
returns owner + situs + mailing + value + parcel + centroid lat/lng — a complete lead, no
name-resolution needed.

Free, anonymous, compliant (public ArcGIS MapServer, no auth/captcha). ~21,288 vacant parcels
of ~117k total, paginated. Gate with FORECLOSURE_GASTON_VACANT=0 to skip.

FIXED 2026-10-03 (extraction-completeness audit, batch 4): the layer's own field list
(``MapServer/11?f=json``) carries six more real, high-value fields this scraper's ``_OUT``
never requested, so they were dropped for free -- no extra request, they ride along in the
SAME bulk query:
  - ``ImagePath`` -- populated on 58.6% of a live 2,000-row sample (NOT a public URL -- it's
    an internal UNC share path, "\\\\GCSQL-DVNT25\\DEVNET\\Images\\ASRIMG\\2019\\984056.JPG").
    Live-confirmed the county's own DevNet Wedge parcel page
    (gastonnc.devnetwedge.com/parcel/view/{PID}/{year}) renders that SAME file from a public
    HTTP path, "/PropertyImages/ASRIMG/2019/984056.JPG" -- i.e. everything in the UNC path
    from "Images\\" onward, backslashes flipped to slashes, served off
    https://gastonnc.devnetwedge.com/PropertyImages/. Verified live on 4 independent samples
    (all 200 image/jpeg, up to 2.1MB) -- real assessor-card property photos, not placeholders.
    Wired into ``raw["images"]["real"]`` (asheville_helene.py's own convention) with zero
    extra requests.
  - ``LEGDESC_1`` -- 100% filled in the same sample, a real legal description (e.g. "WELDON
    HEIGHTS BLK C L 19..."); wired to ``Listing.legal_description`` (was blank on every row).
  - ``DEED_BOOK``/``DEED_PAGE`` -- 100% filled; a real recorded-deed reference. Combined with
    the SALEDATE/SALESAMT this module ALREADY fetches (but only stashed under the private
    ``raw.gaston_gis`` key nothing downstream reads), now also wired into the canonical
    ``raw["gis"]["last_sale"]`` shape (same convention as batch 2's Pickens fix and batch 3's
    Buncombe-elderly fix) so ``enrichment_last_sale.py`` actually surfaces it.
  - ``DEEDTYPE`` -- 98.9% filled (QCD/NWD/etc code); a quitclaim/non-warranty deed is itself a
    distress signal (heir transfer, foreclosure-adjacent conveyance), kept alongside the deed
    reference.
  - ``CURR_NAME2``/``CURR_ADDR2`` -- co-owner name (21.1% filled) and mailing-address line 2
    (15.8% filled); only NAME1/ADDR1 were captured, dropping the second owner on joint-owned
    parcels -- a contactability miss (HERMES Section 9's #1 ceiling).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable

from ...base_scraper import BaseScraper
from ...enrichment_owner_mailing import _is_absentee
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = (
    "https://gis.gastoncountync.gov/publicgis/rest/services/"
    "PublicGIS/Parcels/MapServer/11/query"
)
_WHERE = "VacantImpro='Vacant'"
_OUT = (
    "PIN,PID,WHOLE_ADDRESS,PHYSSTRADD,POSTAL,STATE,ZIP,"
    "JAN1_NAME1,JAN1_NAME2,CURR_NAME1,CURR_NAME2,CURR_ADDR1,CURR_ADDR2,CURR_CITY,"
    "CURR_STATE,CURR_ZIPCODE,"
    "Latitude,Longitude,FMV_TOTAL,FMV_LAND,FMV_IMPRV,TOTVAL,"
    "SALEDATE,SALESAMT,SQFT,YEARBLT,property_use,DESC1_DESC,VacantImpro,CALCAC,DEEDAC,"
    "ImagePath,LEGDESC_1,DEED_BOOK,DEED_PAGE,DEEDTYPE,"
    # 2026-10-07 extraction audit: on the layer, never requested. DEEDQUAL_CODEDESC says
    # whether the last sale was a qualified (arm's-length) one, so SALESAMT can be read as
    # a price or not; EXEMPT_COD marks exempt (government/church) parcels; PRVYRNAME1/2 is
    # the prior year's owner (a recent transfer shows as a change); FLOODAREA the flood flag.
    "DEEDQUAL_CODEDESC,EXEMPT_COD,PRVYRNAME1,PRVYRNAME2,FLOODAREA"
)
_PAGE = 2000
# The county's GIS ImagePath is an internal UNC share path
# ("\\GCSQL-DVNT25\DEVNET\Images\ASRIMG\2019\984056.JPG"); the live DevNet Wedge parcel
# page serves the SAME file publicly at this base + everything after "Images\" (slashes
# flipped). Verified live 2026-10-03 on 4 independent samples.
_DEVNET_IMAGE_BASE = "https://gastonnc.devnetwedge.com/PropertyImages/"


def _image_url(image_path: str | None) -> str | None:
    """Convert a Gaston GIS UNC ImagePath to its public DevNet Wedge photo URL."""
    if not image_path:
        return None
    p = image_path.strip().replace("\\", "/")
    marker = "Images/"
    idx = p.rfind(marker)
    if idx == -1:
        return None
    rel = p[idx + len(marker):].strip("/")
    return f"{_DEVNET_IMAGE_BASE}{rel}" if rel else None


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _coord(v) -> float | None:
    """Lat/lng coercion — NC longitudes are negative, so 0/None is the only reject."""
    try:
        f = float(str(v).strip())
        return f if f != 0 else None
    except (ValueError, TypeError):
        return None


def _i(v) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _owner_mailing_block(a: dict, situs: str | None, parcel: str | None) -> dict | None:
    """raw['owner_mailing'] in the pipeline's standard shape, from the CURR_* columns."""
    addr = ", ".join(x for x in (_s(a.get("CURR_ADDR1")), _s(a.get("CURR_ADDR2"))) if x)
    city, st, z = _s(a.get("CURR_CITY")), _s(a.get("CURR_STATE")), _s(a.get("CURR_ZIPCODE"))
    tail = " ".join(x for x in (city, st, z) if x)
    mailing = ", ".join(x for x in (addr, tail) if x) or None
    if not mailing:
        return None
    mail_state = (st or "").upper() or None
    owner = " & ".join(x for x in (_s(a.get("CURR_NAME1")), _s(a.get("CURR_NAME2"))) if x) or None
    return {
        "owner": owner, "mailing": mailing, "situs": situs, "parcel_id": parcel,
        "mail_state": mail_state,
        "absentee": _is_absentee(situs, mailing),
        "out_of_state": bool(mail_state and mail_state != "NC"),
        "source": "gaston_county_gis",
    }


def _epoch_ms_to_dt(v) -> datetime | None:
    """SALEDATE arrives as epoch-milliseconds (Esri date)."""
    try:
        ms = float(v)
        if ms <= 0:
            return None
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


class GastonVacant(BaseScraper):
    slug = "counties_nc.gaston_vacant"
    name = "Gaston County (NC) Vacant Parcels"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_GASTON_VACANT", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 60000:  # hard backstop; real set ~21,288
                params = {
                    "where": _WHERE,
                    "outFields": _OUT,
                    "returnGeometry": "false",
                    "resultRecordCount": str(_PAGE),
                    "resultOffset": str(offset),
                    "orderByFields": "PID",
                    "f": "json",
                }
                try:
                    r = await c.get(QUERY_URL, params=params)
                    if r.status_code != 200:
                        break
                    feats = r.json().get("features", []) or []
                except Exception:  # noqa: BLE001
                    break
                if not feats:
                    break
                for ft in feats:
                    a = ft.get("attributes", {}) or {}
                    pin = _s(a.get("PIN"))
                    pid = _s(a.get("PID"))
                    owner = _s(a.get("JAN1_NAME1"))
                    if not (pin or pid):
                        continue
                    situs = _s(a.get("WHOLE_ADDRESS")) or _s(a.get("PHYSSTRADD"))
                    zip_raw = a.get("ZIP")
                    zip_code = _s(str(zip_raw)) if zip_raw not in (None, "", 0) else None
                    if zip_code and len(zip_code) == 9:  # 9-digit ZIP+4 stored as int
                        zip_code = zip_code[:5]
                    owner2 = _s(a.get("JAN1_NAME2"))
                    if owner and owner2:
                        owner = f"{owner} & {owner2}"
                    last_sale_dt = _epoch_ms_to_dt(a.get("SALEDATE"))
                    last_sale_amt = _f(a.get("SALESAMT"))
                    legal_desc = _s(a.get("LEGDESC_1"))
                    photo_url = _image_url(_s(a.get("ImagePath")))
                    raw_payload: dict = {"gaston_gis": {
                        "signal": "vacant_parcel",
                        "life_event": "vacant_land",
                        "VacantImpro": _s(a.get("VacantImpro")),
                        "DESC1_DESC": _s(a.get("DESC1_DESC")),
                        "property_use": _s(a.get("property_use")),
                        "PIN": pin,
                        "PID": pid,
                        "FMV_TOTAL": _f(a.get("FMV_TOTAL")),
                        "FMV_LAND": _f(a.get("FMV_LAND")),
                        "FMV_IMPRV": _f(a.get("FMV_IMPRV")),
                        "SALESAMT": last_sale_amt,
                        # NOT the Listing's own sale_date: SALEDATE is the county's last
                        # recorded TRANSACTION date (when the current owner acquired the
                        # parcel), not a scheduled foreclosure auction. This source is a
                        # STANDING vacant-land distress signal with no scheduled event (it's
                        # in main.py's DATELESS_OK_SOURCES for exactly that reason) -- setting
                        # it as Listing.sale_date made _active_only() drop every row as a
                        # "sale more than 14 days in the past" even though the whitelist entry
                        # existed, since that check only applies when sale_date is None.
                        # Found 2026-09-15: this bug was why 21,299 real, live rows never
                        # reached the board despite the scraper working correctly.
                        "last_sale_date": last_sale_dt.isoformat() if last_sale_dt else None,
                        "deed_book": _s(a.get("DEED_BOOK")),
                        "deed_page": _s(a.get("DEED_PAGE")),
                        "deed_type": _s(a.get("DEEDTYPE")),
                        "deed_qualification": _s(a.get("DEEDQUAL_CODEDESC")),
                        "exempt_code": _s(a.get("EXEMPT_COD")),
                        "prior_year_owner": _s(a.get("PRVYRNAME1")),
                        "prior_year_owner2": _s(a.get("PRVYRNAME2")),
                        "flood_area": _s(a.get("FLOODAREA")),
                        "legal_description": legal_desc,
                        "owner_mailing": {
                            "name": _s(a.get("CURR_NAME1")),
                            "name2": _s(a.get("CURR_NAME2")),
                            "addr": _s(a.get("CURR_ADDR1")),
                            "addr2": _s(a.get("CURR_ADDR2")),
                            "city": _s(a.get("CURR_CITY")),
                            "state": _s(a.get("CURR_STATE")),
                            "zip": _s(a.get("CURR_ZIPCODE")),
                        },
                    }}
                    # Canonical shape enrichment_last_sale.py actually reads -- the SAME
                    # SALEDATE/SALESAMT above, just also surfaced where the enricher looks.
                    if last_sale_dt and last_sale_amt:
                        raw_payload["gis"] = {"last_sale": {
                            "date": last_sale_dt.isoformat(),
                            "amount": last_sale_amt,
                            "source": "gaston_gis",
                        }}
                        # the county's own sale-qualification code for this sale
                        if _s(a.get("DEEDQUAL_CODEDESC")):
                            raw_payload["gis"]["last_sale"]["qualification"] = _s(
                                a.get("DEEDQUAL_CODEDESC"))
                    # The standard top-level owner_mailing block. The CURR_* mailing above
                    # lived only inside raw.gaston_gis, and mailing_shape.mailing_of (the
                    # scorer, skip-trace, mail merge) reads raw['owner_mailing'] only, so the
                    # ~2/3 of rows the owner-mailing enricher never reached carried no
                    # absentee/out-of-state signal at all. Same shape and helper as
                    # henderson_foreclosure_parcels; the enricher skips a row that has it.
                    om = _owner_mailing_block(a, situs, pin or pid)
                    if om:
                        raw_payload["owner_mailing"] = om
                    if photo_url:
                        raw_payload["images"] = {"real": [photo_url]}
                    out.append(Listing(
                        source=self.slug,
                        source_url=(
                            f"{QUERY_URL}?where=PIN%3D%27{(pin or '').replace(' ', '+')}%27"
                            "&outFields=*&f=html"
                        ),
                        listing_type=ListingType.DISTRESSED,
                        property_kind=PropertyKind.LAND,
                        owner_name=owner,
                        street_address=situs,
                        city=(_s(a.get("POSTAL")) or "").title() or None,
                        state=_s(a.get("STATE")) or "NC",
                        county="Gaston",
                        zip_code=zip_code,
                        parcel_id=pin or pid,
                        latitude=_coord(a.get("Latitude")),
                        longitude=_coord(a.get("Longitude")),
                        market_value=_f(a.get("FMV_TOTAL")),
                        assessed_value=_f(a.get("TOTVAL")),
                        tax_value=_f(a.get("TOTVAL")),
                        living_sqft=_f(a.get("SQFT")),
                        year_built=_i(a.get("YEARBLT")),
                        acreage=_f(a.get("CALCAC")) or _f(a.get("DEEDAC")),
                        land_use=_s(a.get("property_use")),
                        legal_description=legal_desc,
                        description=(
                            "Vacant parcel (no improvements on record) per county GIS "
                            "VacantImpro flag — absentee / holding-cost distress signal; "
                            "mailing address often out-of-county."
                        ),
                        first_seen=now,
                        last_seen=now,
                        raw=raw_payload,
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
