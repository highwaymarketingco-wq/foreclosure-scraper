"""Lexington County SC homestead exemption (elderly/disabled/blind) — the SAME
SC Code 12-37-250 signal as counties_sc.york_homestead.py, on this county's own
CAMA vendor/schema (Homestead='YES'/'NO' rather than York's 'Y'/'N'). See that
module's docstring for the full rationale (property-keyed, one bulk query,
why this is not a duplicate of enrichment_tax_relief.py's existing per-lead
Lexington lookup, and the raw['tax_relief'] shape that feeds distress_score's
"senior_exemption" signal with no further scoring change needed).

ENDPOINT (free, anonymous, no auth/captcha/paywall -- live-verified 2026-11-11):
  https://maps.lex-co.com/agstserver/rest/services/Property/MapServer/4/query
  WHERE Homestead='YES' -> 28,277 live parcels (2026-11-11; enrichment_tax_relief.py's
  own docstring measured 28,112 on 2026-10-30). maxRecordCount 10000 (live-
  verified) -- still paged at 2000 for parity with every other scraper in this
  tree and to stay well clear of the layer's own cap.

UNLIKE YORK, this layer carries a full situs breakdown (PropAddr_Num/_Str/_Suf
plus PropAddr_City/_State/_Zip, live-verified 2026-11-11) -- city/zip_code are
populated directly from it, not inferred from the owner's mailing address.

NOT COVERED -- deliberately scoped to the homestead exemption only. This
layer's AG='AG YES' (agricultural use-value, a present-use ROLLBACK liability,
a different signal, same statute shape as York's LandUseDesc FARM match)
stays enrichment_tax_relief.py's job alone.

Gate with FORECLOSURE_LEXINGTON_HOMESTEAD_SOURCE=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://maps.lex-co.com/agstserver/rest/services/Property/MapServer/4/query"
_WHERE = "Homestead='YES'"
_OUT = ("TMS,TMS_No_Dash,Owner,PropAddr_Num,PropAddr_Str,PropAddr_Suf,PropAddr_City,"
        "PropAddr_State,PropAddr_Zip,MailAddr,MailAddr2,MailAddr3,MailAddr_City,"
        "MailAddr_State,MailAddr_Zip,MktTotal,TaxableTotal,Acres,PropTypeDesc,Homestead")
_PAGE = 2000


def _source_url(tms: str) -> str:
    where = f"TMS%3D%27{tms}%27"
    return f"{QUERY_URL}?where={where}&outFields=*&f=html"


def _s(v) -> str | None:
    return str(v).strip() or None if v not in (None, "") else None


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _situs(a: dict) -> str | None:
    parts = [_s(a.get("PropAddr_Num")), _s(a.get("PropAddr_Str")), _s(a.get("PropAddr_Suf"))]
    return " ".join(p for p in parts if p) or None


def _owner_mailing(a: dict, owner: str, tms: str, situs: str | None) -> dict | None:
    street = " ".join(p for p in (_s(a.get("MailAddr")), _s(a.get("MailAddr2")),
                                   _s(a.get("MailAddr3"))) if p)
    city = _s(a.get("MailAddr_City")) or ""
    state = (_s(a.get("MailAddr_State")) or "").upper()[:2] or None
    zipc = _s(a.get("MailAddr_Zip")) or ""
    mailing = " ".join(b for b in (street, city, state or "", zipc) if b) or None
    if not mailing:
        return None
    same = bool(situs and street and street.upper() == situs.upper())
    return {
        "owner": owner, "mailing": mailing, "situs": situs, "parcel_id": tms,
        "mail_state": state,
        "absentee": (not same) if situs else None,
        "out_of_state": bool(state and state != "SC"),
        "source": "lexington_homestead_gis",
    }


class LexingtonHomestead(BaseScraper):
    slug = "counties_sc.lexington_homestead"
    name = "Lexington County (SC) Homestead Exemption (Elderly/Disabled/Blind)"
    category = "motivated_seller"
    timeout_s = 180.0
    expected_min_count = 15000

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_LEXINGTON_HOMESTEAD_SOURCE", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 60000:  # hard backstop; real set ~28,300
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "TMS", "f": "json"}
                try:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential_jitter(initial=1, max=8),
                        retry=retry_if_exception_type(
                            (httpx.TransportError, httpx.TimeoutException, TimeoutError)
                        ),
                        reraise=True,
                    ):
                        with attempt:
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
                    owner = _s(a.get("Owner"))
                    tms = _s(a.get("TMS")) or _s(a.get("TMS_No_Dash"))
                    if not owner or not tms:
                        continue
                    situs = _situs(a)
                    city = _s(a.get("PropAddr_City"))
                    zipc = _s(a.get("PropAddr_Zip"))
                    land_use = _s(a.get("PropTypeDesc")) or ""
                    pk = PropertyKind.SINGLE_FAMILY if "RES" in land_use.upper() \
                        else PropertyKind.UNKNOWN

                    raw = {
                        "gis_exempt": {"code": "HOMESTEAD", "tag": "sc_homestead_exemption"},
                        "life_event": "elderly_disabled_homestead",
                        "tax_relief": {"kind": "homestead_exemption",
                                       "basis": "sc_homestead_age65_disabled",
                                       "deferred_value": None, "county": "Lexington"},
                    }
                    raw["owner_mailing"] = _owner_mailing(a, owner, tms, situs)

                    out.append(Listing(
                        source=self.slug,
                        source_url=_source_url(tms),
                        listing_type=ListingType.ELDERLY_DISABLED,
                        property_kind=pk,
                        owner_name=owner,
                        street_address=situs,
                        city=(city.title() if city else None),
                        state="SC",
                        zip_code=zipc,
                        county="Lexington",
                        parcel_id=tms,
                        market_value=_f(a.get("MktTotal")),
                        assessed_value=_f(a.get("TaxableTotal")),
                        land_use=land_use or None,
                        acreage=_f(a.get("Acres")),
                        description="SC homestead property-tax exemption on file "
                                    "(owner age 65+/disabled/blind property-tax relief).",
                        first_seen=now,
                        last_seen=now,
                        raw=raw,
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
