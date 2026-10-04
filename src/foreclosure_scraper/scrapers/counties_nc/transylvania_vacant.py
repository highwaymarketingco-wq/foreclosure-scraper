"""Transylvania County NC vacant-land parcels — a PROPERTY-KEYED motivated-seller source.

The county parcel FeatureServer carries a per-parcel building value (BUILDING_V). Parcels with
BUILDING_V=0 are unimproved / vacant land — a classic motivated-seller cohort (out-of-area owners,
inherited lots, tax-burdened holds). One bulk ArcGIS query returns owner + situs (LEGAL_ADDR) +
land value + parcel PIN + sale history, so each row is a complete property-keyed lead with no
name-resolution step.

Note: ADDRESS_1/2/3 + CITY/STATE/ZIP are the OWNER MAILING address (frequently out of county/state);
LEGAL_ADDR is the in-county situs/property location. We key the listing to the situs and stash the
owner mailing block in raw.

Free, anonymous, compliant (public ArcGIS, no auth/captcha). ~11,131 vacant parcels, paginated.
Gate with FORECLOSURE_TRANSYLVANIA_VACANT=0 to skip.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://gis.transylvaniacounty.org/server/rest/services/Parcels/FeatureServer/2/query"
_WHERE = "BUILDING_V=0 AND OWNER_NAME IS NOT NULL"
# 2026-10-03: added WATERFRONT, ACCOUNT_NO, SALE_INST/SALE_QUALI/SALE_IMP and
# XFOB_VALUE -- all already on the live 65-field layer, none previously
# requested. Live-sampled 500 rows: WATERFRONT=Y on 8 (1.6%, a real value
# driver for "vacant" land), SALE_QUALI/SALE_INST carry real qualification/
# instrument codes (a QC/quitclaim or non-qualifying sale is NOT a comp --
# the old code fed raw SALE_PRICE to raw['gis']['last_sale'] with no way to
# tell), SALE_IMP='I' on 13/500 despite BUILDING_V=0 today (the parcel WAS
# improved at the time of its last sale -- a demolished/burned structure, a
# distinct signal from always-vacant land), and XFOB_VALUE nonzero on 20/500
# (a well/septic/outbuilding not counted in BUILDING_V=0).
_OUT = ("PIN,OWNER_NAME,ADDRESS_1,ADDRESS_2,ADDRESS_3,CITY,STATE,ZIP_CODE,LEGAL_ADDR,"
        "USECODE,ZONING,ACRES,HEATED_SQ_,AYB,SALE_PRICE,SALE_DATE,SALE_INST,SALE_QUALI,"
        "SALE_IMP,LAND_VALUE,ASSESSED_V,BUILDING_V,XFOB_VALUE,WATERFRONT,ACCOUNT_NO,"
        "DEED_BK,PAGE,Report_URL")
_PAGE = 2000


def _is_absentee(mail_state: str | None, mail_street: str | None, situs: str | None) -> bool:
    """Owner mails from out of state, from a PO box, or from a different street
    than the parcel. Same three tells as counties_sc.pickens_delinquent_parcels
    and counties_nc.lincoln_vacant, with the SAME guard lincoln_vacant needed:
    live-sampled 2,000 rows here, only 5 (0.25%) of LEGAL_ADDR values start
    with a house number -- vacant land's situs is almost always just a road
    name ("CASHIERS RD"), so comparing leading street tokens unconditionally
    would call nearly every owner "absentee" on that formatting mismatch
    alone, not a real signal. The street-token comparison only runs when situs
    itself carries a house number."""
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


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _build_raw(a: dict, situs: str | None, mailing: dict, mail_street: str | None,
               mail_city: str | None, mail_state: str | None,
               sale_amt: float | None, sale_dt: str | None) -> dict:
    raw: dict = {"transylvania_vacant": {
        "building_value": a.get("BUILDING_V"),
        "land_value": a.get("LAND_VALUE"),
        "assessed_value": a.get("ASSESSED_V"),
        "sale_price": a.get("SALE_PRICE"),
        "sale_date": _s(a.get("SALE_DATE")),
        "sale_instrument": _s(a.get("SALE_INST")),
        "sale_qualifying_code": _s(a.get("SALE_QUALI")),
        "sale_improved_at_sale": _s(a.get("SALE_IMP")),
        "deed_book": _s(a.get("DEED_BK")),
        "deed_page": _s(a.get("PAGE")),
        "usecode": _s(a.get("USECODE")),
        "acres": a.get("ACRES"),
        "waterfront": _s(a.get("WATERFRONT")),
        "account_number": _s(a.get("ACCOUNT_NO")),
        "extra_features_value": _f(a.get("XFOB_VALUE")),
        "owner_mailing": mailing,
        "signal": "vacant_land",
    }}
    # raw['owner_mailing'] (top-level) is the key enrichment_lead_signals.py's
    # absentee_owner/out_of_state_owner check, enrichment_skip_trace.py and
    # enrichment_notice_service_defect.py all read (mailing_shape.mailing_of)
    # -- the old code only stashed this under
    # raw['transylvania_vacant']['owner_mailing'], where none of them look.
    if mail_street or mail_city:
        raw["owner_mailing"] = mailing
        if _is_absentee(mail_state, mail_street, situs):
            raw["absentee_owner"] = True
    # SALE_PRICE + SALE_DATE already fetched but never paired into the
    # canonical raw['gis']['last_sale'] key enrichment_last_sale.py reads
    # (same convention as lincoln_vacant.py's own 2026-10-03 fix).
    if sale_amt and sale_dt:
        raw["gis"] = {"last_sale": {
            "amount": sale_amt, "date": sale_dt,
            "source": "transylvania_county_gis",
        }}
    return raw


class TransylvaniaVacant(BaseScraper):
    slug = "counties_nc.transylvania_vacant"
    name = "Transylvania County (NC) Vacant Land"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_TRANSYLVANIA_VACANT", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 60000:  # hard backstop; real set ~11,131
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "OBJECTID", "f": "json"}
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
                    owner = _s(a.get("OWNER_NAME"))
                    if not pin or not owner:
                        continue
                    situs = _s(a.get("LEGAL_ADDR"))
                    year = None
                    try:
                        ay = int(str(a.get("AYB")).strip())
                        year = ay if 1700 < ay < 2100 else None
                    except (ValueError, TypeError):
                        year = None
                    # Live-sampled 2026-10-03: ADDRESS_1 is usually a CO-OWNER
                    # name or a trustee/attn line ("Bruce Dorothy C Trustees",
                    # "CO-TRUSTEE", "%Karen Mcleod President"), not a street --
                    # keeping it in the "street" slot (the old code's labeling)
                    # would publish a person's name as a mailing street. The
                    # actual deliverable street can land in EITHER ADDRESS_2 or
                    # ADDRESS_3 depending on how many lines the record needed
                    # (a suite number alone sometimes rides in ADDRESS_3 with
                    # the real street in ADDRESS_2), so both are joined.
                    mail_co_owner_or_attn = _s(a.get("ADDRESS_1"))
                    mail_street = ", ".join(
                        p for p in (_s(a.get("ADDRESS_2")), _s(a.get("ADDRESS_3"))) if p
                    ) or None
                    mail_city = _s(a.get("CITY"))
                    mail_state = _s(a.get("STATE"))
                    mail_zip = _s(a.get("ZIP_CODE"))
                    mailing = {
                        "owner_line2": mail_co_owner_or_attn,
                        "street": mail_street,
                        "city": mail_city,
                        "state": mail_state,
                        "zip": mail_zip,
                    }
                    sale_amt = _f(a.get("SALE_PRICE"))
                    sale_dt = _s(a.get("SALE_DATE"))
                    out.append(Listing(
                        source=self.slug,
                        source_url=(_s(a.get("Report_URL"))
                                    or f"{QUERY_URL}?where=PIN%3D%27{pin}%27&outFields=*&f=html"),
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.LAND,
                        owner_name=owner,
                        street_address=situs,
                        city=None,  # CITY/STATE/ZIP are owner mailing, not situs
                        state="NC",
                        county="Transylvania",
                        zip_code=None,
                        parcel_id=pin,
                        legal_description=situs,
                        zoning=_s(a.get("ZONING")),
                        acreage=_f(a.get("ACRES")),
                        living_sqft=_f(a.get("HEATED_SQ_")),
                        year_built=year,
                        land_use=_s(a.get("USECODE")),
                        assessed_value=_f(a.get("ASSESSED_V")),
                        market_value=_f(a.get("LAND_VALUE")),
                        description="Vacant/unimproved parcel (building value $0) — motivated-seller "
                                    "cohort (out-of-area/inherited/tax-burdened land holds).",
                        first_seen=now,
                        last_seen=now,
                        raw=_build_raw(a, situs, mailing, mail_street, mail_city,
                                       mail_state, sale_amt, sale_dt),
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
