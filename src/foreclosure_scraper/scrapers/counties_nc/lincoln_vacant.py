"""Lincoln County NC vacant parcels — a PROPERTY-KEYED motivated-seller source.

The county ComDev parcel layer carries a VACANT flag per parcel. Vacant (unimproved /
no-structure) parcels held by out-of-area or long-hold owners are prime motivated-seller
prospects (nothing to maintain, carrying cost with no income, often inherited raw land).
Like the elderly/exemption lane this is property-keyed: ONE bulk query returns owner +
situs address + mailing + value + parcel, a complete lead with no name-resolution needed.

Free, anonymous, compliant (public ArcGIS REST, no auth/captcha). ~14,798 vacant parcels,
paginated. GOTCHA: the host's TLS cert is EXPIRED, so we hit it with httpx verify=False.
Gate with FORECLOSURE_LINCOLN_VACANT=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

import httpx

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://arcgisserver.lincolncounty.org/arcgis/rest/services/ComDevData/MapServer/25/query"
_WHERE = "VACANT='YES'"
_OUT = "PARCELID,PIN,PHYSICALADDR,NAME1,ADDRESS1,IMPROVALUE,TOTALVALUE,MAINAREASQFT,SALEPRICE"
_PAGE = 2000


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


class LincolnVacant(BaseScraper):
    slug = "counties_nc.lincoln_vacant"
    name = "Lincoln County (NC) Vacant Parcels"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_LINCOLN_VACANT", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        # Host TLS cert is expired -> verify=False (public read-only GIS endpoint).
        async with httpx.AsyncClient(verify=False, timeout=60.0) as c:
            offset = 0
            while offset < 200000:  # hard backstop; real set ~14,798
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "PARCELID", "f": "json"}
                try:
                    r = await c.get(QUERY_URL, params=params)
                    if r.status_code != 200:
                        break
                    body = r.json()
                    feats = body.get("features", []) or []
                except Exception:  # noqa: BLE001
                    break
                if not feats:
                    break
                more = bool(body.get("exceededTransferLimit"))
                for ft in feats:
                    a = ft.get("attributes", {}) or {}
                    parcel = (str(a.get("PARCELID") or "").strip() or None)
                    pin = (str(a.get("PIN") or "").strip() or None)
                    situs = (str(a.get("PHYSICALADDR") or "").strip() or None)
                    owner = (str(a.get("NAME1") or "").strip() or None)
                    if not parcel and not pin:
                        continue
                    out.append(Listing(
                        source=self.slug,
                        source_url=(f"{QUERY_URL}?where=PARCELID%3D%27{parcel}%27&outFields=*&f=html"
                                    if parcel else f"{QUERY_URL}?where={_WHERE}&outFields=*&f=html"),
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.LAND,
                        owner_name=owner,
                        street_address=situs,
                        state="NC",
                        county="Lincoln",
                        parcel_id=parcel or pin,
                        living_sqft=_f(a.get("MAINAREASQFT")),
                        assessed_value=_f(a.get("TOTALVALUE")),
                        market_value=_f(a.get("TOTALVALUE")),
                        description="County parcel flagged VACANT (unimproved / no structure) — "
                                    "carrying-cost motivated-seller signal.",
                        first_seen=now,
                        last_seen=now,
                        raw={"lincoln_vacant": {
                            "PARCELID": parcel, "PIN": pin, "PHYSICALADDR": situs,
                            "NAME1": owner, "ADDRESS1": (str(a.get("ADDRESS1") or "").strip() or None),
                            "IMPROVALUE": a.get("IMPROVALUE"), "TOTALVALUE": a.get("TOTALVALUE"),
                            "MAINAREASQFT": a.get("MAINAREASQFT"), "SALEPRICE": a.get("SALEPRICE"),
                            "signal": "vacant_parcel"},
                        },
                    ))
                offset += len(feats)
                # Server caps each page below _PAGE; keep paging while it flags more.
                if not more and len(feats) < _PAGE:
                    break
        return out
