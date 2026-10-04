"""Lincoln County NC vacant parcels — a PROPERTY-KEYED motivated-seller source.

The county ComDev parcel layer carries a VACANT flag per parcel. Vacant (unimproved /
no-structure) parcels held by out-of-area or long-hold owners are prime motivated-seller
prospects (nothing to maintain, carrying cost with no income, often inherited raw land).
Like the elderly/exemption lane this is property-keyed: ONE bulk query returns owner +
situs address + mailing + value + parcel, a complete lead with no name-resolution needed.

Free, anonymous, compliant (public ArcGIS REST, no auth/captcha). ~14,798 vacant parcels,
paginated. GOTCHA: the host's TLS cert is EXPIRED, so we hit it with httpx verify=False.
Gate with FORECLOSURE_LINCOLN_VACANT=0 to skip.

2026-10-03 (HERMES extraction-completeness audit, batch 5): the docstring above already
claimed "mailing" was part of the bulk query, but the code never actually fetched CITY/
STATE/ZIP or surfaced ADDRESS1 beyond a private raw key -- there was no way to tell an
in-county owner from one mailing out of state. Now wired: raw['owner_mailing'] + a
(guarded) raw['absentee_owner'] flag, raw['gis']['last_sale'] (SALEPRICE paired with the
previously-uncaptured SDATE), deed/plat reference, and co-owner (NAME2). See
tests/test_lincoln_vacant.py for the live-verified fill rates and the absentee-heuristic
false-positive guard (vacant land's situs usually has no house number).
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import httpx

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://arcgisserver.lincolncounty.org/arcgis/rest/services/ComDevData/MapServer/25/query"
_WHERE = "VACANT='YES'"
# NAME2/ADDRESS2/CITY/STATE/ZIP/DEEDBK/DEEDPG/DEEDYR/PLATBK/PLATPG/SDATE/SBDIVN added
# 2026-10-03 (HERMES extraction-completeness audit, batch 5). Diffed the live 55-field
# layer schema against the old 9-field outFields list: CITY/STATE/ZIP (the owner's own
# MAILING address, live-sampled as 499/500 filled) were never even REQUESTED, let alone
# surfaced -- a glaring miss given this scraper's entire stated purpose is flagging
# "out-of-area... owners" as motivated-seller prospects, yet nothing in the old code
# could tell an in-county owner from one mailing from Boca Raton FL. ADDRESS1 WAS already
# fetched but only stashed under the private raw["lincoln_vacant"] key nothing downstream
# reads (same miss class as batch 4's Gaston SALEDATE/SALESAMT). DEEDBK/DEEDPG/DEEDYR
# (100% filled) is a real deed reference; SDATE (100% filled) is the last-sale DATE —
# SALEPRICE was already captured but its paired date was not, so enrichment_last_sale's
# raw['gis']['last_sale'] key was unreachable even when a real sale amount existed.
# NAME2 (51% filled) is a co-owner dropped on jointly-owned parcels. PLATBK/PLATPG (31%)
# is a plat reference. SBDIVN (subdivision name, ~100% filled though often blank-string)
# is minor context, kept in raw only.
_OUT = ("PARCELID,PIN,PHYSICALADDR,NAME1,NAME2,ADDRESS1,ADDRESS2,CITY,STATE,ZIP,"
        "IMPROVALUE,TOTALVALUE,MAINAREASQFT,SALEPRICE,SDATE,DEEDBK,DEEDPG,DEEDYR,"
        "PLATBK,PLATPG,SBDIVN")
_PAGE = 2000


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _s(v) -> str | None:
    s = str(v or "").strip()
    return s or None


def _is_absentee(mail_state: str | None, mail_street: str | None, situs: str | None) -> bool:
    """Owner mails from out of state, from a PO box, or from a different street
    than the parcel. Mirrors counties_sc.pickens_delinquent_parcels._is_absentee
    (same three tells), with ONE guard added for this specific dataset: VACANT
    land's PHYSICALADDR is usually just a road name with NO house number
    ("CAT SQUARE RD"), while the mailing street always starts with one ("7347
    HENRY RD") -- live-sampled, only 1,251/14,731 situs values here start with a
    digit. Comparing leading tokens unconditionally (the Pickens original) would
    call ~99% of this specific dataset "absentee" on that formatting mismatch
    alone, not a real signal (live-verified: 14,575/14,731 before this guard vs.
    893 out-of-state + 1,157 PO-box after it) -- exactly the false-positive-
    inflation failure mode flagged in project_signal_accuracy_validation, so the
    street-token comparison only runs when situs itself carries a house number."""
    st = (mail_state or "").strip().upper()
    if st and st != "NC":
        return True
    street = (mail_street or "").strip().upper()
    if re.search(r"\bP\.?\s?O\.?\s?BOX\b", street):
        return True
    if street and situs and re.match(r"^\d", situs.strip()):
        a = re.sub(r"\s+", " ", street).split()
        b = re.sub(r"\s+", " ", situs.strip().upper()).split()
        if a[:2] != b[:2]:
            return True
    return False


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

                    mail_street = _s(a.get("ADDRESS1"))
                    mail_street2 = _s(a.get("ADDRESS2"))
                    mail_city = _s(a.get("CITY"))
                    mail_state = _s(a.get("STATE"))
                    mail_zip = _s(a.get("ZIP"))
                    sale_amt = _f(a.get("SALEPRICE"))
                    sale_dt = _s(a.get("SDATE"))

                    raw: dict = {"lincoln_vacant": {
                        "PARCELID": parcel, "PIN": pin, "PHYSICALADDR": situs,
                        "NAME1": owner, "NAME2": _s(a.get("NAME2")),
                        "ADDRESS1": mail_street, "ADDRESS2": mail_street2,
                        "CITY": mail_city, "STATE": mail_state, "ZIP": mail_zip,
                        "IMPROVALUE": a.get("IMPROVALUE"), "TOTALVALUE": a.get("TOTALVALUE"),
                        "MAINAREASQFT": a.get("MAINAREASQFT"), "SALEPRICE": a.get("SALEPRICE"),
                        "co_owner": _s(a.get("NAME2")),
                        "deed_book": _s(a.get("DEEDBK")), "deed_page": _s(a.get("DEEDPG")),
                        "deed_year": a.get("DEEDYR"),
                        "plat_book": _s(a.get("PLATBK")), "plat_page": _s(a.get("PLATPG")),
                        "subdivision": _s(a.get("SBDIVN")),
                        "signal": "vacant_parcel"},
                    }
                    if mail_street or mail_city:
                        raw["owner_mailing"] = {
                            "street": mail_street, "street2": mail_street2,
                            "city": mail_city, "state": mail_state, "zip": mail_zip,
                            "source": "lincoln_county_gis",
                        }
                        if _is_absentee(mail_state, mail_street, situs):
                            raw["absentee_owner"] = True
                    # SALEPRICE is already fetched but was never paired with its own
                    # SDATE -- enrichment_last_sale.py's raw['gis']['last_sale'] key
                    # needs BOTH to surface a recorded-sale fact (same $0 = "no
                    # arms-length sale" guard _f() already applies via its >0 check).
                    if sale_amt and sale_dt:
                        raw["gis"] = {"last_sale": {
                            "amount": sale_amt, "date": sale_dt,
                            "source": "lincoln_county_gis",
                        }}

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
                        raw=raw,
                    ))
                offset += len(feats)
                # Server caps each page below _PAGE; keep paging while it flags more.
                if not more and len(feats) < _PAGE:
                    break
        return out
