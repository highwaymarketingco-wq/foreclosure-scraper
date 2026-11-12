"""York County SC homestead exemption (elderly/disabled/blind) — a PROPERTY-KEYED
motivated-seller source, the SC analog of counties_nc.buncombe_elderly.py.

SC Code 12-37-250 excludes the first $50,000 of a legal residence's fair market
value for an owner who is 65+, totally and permanently disabled, or legally
blind. York's own parcel layer carries this as a per-parcel HOMESTEAD flag.
Those owners are prime motivated-seller prospects for the same reason Buncombe's
elderly/disabled homeowners are (downsizing, can't maintain, heirs about to
inherit) -- unlike a name-indexed lane, this is property-keyed: one bulk query
returns owner + address + value + parcel, a complete lead, no name resolution.

THIS IS NOT A DUPLICATE OF enrichment_tax_relief.py's existing York entry.
That module only QUERIES this fact for leads that already resolved a parcel_id
from some OTHER source (tax lien, foreclosure, etc) -- a small, capped,
per-lead lookup. It never sources a lead on its own. This scraper is the
full-county BULK SWEEP (every one of the ~80,600 homesteaded parcels becomes
its own lead, same as Buncombe's elderly scraper), which is the only way the
tens of thousands of homesteaded owners who carry no OTHER distress signal ever
reach the board at all. Both mechanisms can run side by side without
contradiction: this scraper's own rows satisfy enrichment_tax_relief's
`not (li.raw or {}).get("tax_relief")` skip-if-already-tagged guard, so it
never re-queries a row this scraper already tagged.

raw['tax_relief'] is written in the EXACT shape enrichment_tax_relief.py's own
`_classify()` "york_sc" path produces ({"kind": "homestead_exemption", "basis":
"sc_homestead_age65_disabled", "deferred_value": None, "county": "York"}) so
distress_score._collect's existing "senior_exemption" signal path (fixed
2026-11-10 to recognize kind=="homestead_exemption") scores these rows with NO
further scoring change needed. raw['gis_exempt'] mirrors Buncombe's own shape
for the same reason (symmetry with the existing elderly_disabled verifier
family, even though that verifier's applies() is Buncombe-only and will not
try to verify these rows).

ENDPOINT (free, anonymous, no auth/captcha/paywall -- live-verified 2026-11-11):
  https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Parcels/FeatureServer/0/query
  WHERE HOMESTEAD='Y' -> 80,611 live parcels (2026-11-11; enrichment_tax_relief.py's
  own docstring measured 80,620 on 2026-10-02 -- the ~0.01% drift is ordinary
  churn, not a different field). maxRecordCount 2000 (live-verified), so the
  same offset-paging shape as buncombe_elderly.py is required.

NOT COVERED -- deliberately scoped to the elderly/disabled/blind exemption
only. York's LandUseDesc LIKE '%FARM%' (agricultural use-value, a present-use
ROLLBACK liability, a different signal) stays enrichment_tax_relief.py's job
alone; mixing it into this scraper's WHERE would conflate two distinct
motivated-seller signals under one listing_type.

NO SITUS CITY/ZIP ON THIS LAYER -- live field-schema check (2026-11-11, 67
fields) confirmed PropertyAddress is the parcel's only situs column (no
PropertyCity/PropertyZip exist at all, unlike Lexington's layer below). city/
zip_code are left unset rather than fabricated from the owner's mailing
address, which is frequently a different household entirely for an elderly
owner (a relative's address, a care facility).

Gate with FORECLOSURE_YORK_HOMESTEAD_SOURCE=0 to skip.
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

QUERY_URL = "https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Parcels/FeatureServer/0/query"
_WHERE = "HOMESTEAD='Y'"
_OUT = ("ParcelID,TAXMAPID,Owner1,Owner2,Owner3,PropertyAddress,MailAddr1,MailAddr2,"
        "MailCity,MailState,MailZip,AprTotVal,TaxTotVal,LandUseDesc,deededacres,HOMESTEAD")
_PAGE = 2000  # the layer's own maxRecordCount (live-verified 2026-11-11)


def _source_url(parcel_id: str) -> str:
    where = f"ParcelID%3D%27{parcel_id}%27"
    return f"{QUERY_URL}?where={where}&outFields=*&f=html"


def _s(v) -> str | None:
    return str(v).strip() or None if v not in (None, "") else None


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _owner(a: dict) -> str | None:
    names = [n for n in (_s(a.get("Owner1")), _s(a.get("Owner2")), _s(a.get("Owner3"))) if n]
    return "; ".join(names) or None


def _owner_mailing(a: dict, owner: str, parcel_id: str, situs: str | None) -> dict | None:
    """owner_mailing shape other consumers (mailing_shape.mailing_of, the
    absentee/contact enrichers) read. None when the layer has no mailing."""
    street = " ".join(p for p in (_s(a.get("MailAddr1")), _s(a.get("MailAddr2"))) if p)
    city = (_s(a.get("MailCity")) or "")
    state = (_s(a.get("MailState")) or "").upper()[:2] or None
    zipc = _s(a.get("MailZip")) or ""
    mailing = " ".join(b for b in (street, city, state or "", zipc) if b) or None
    if not mailing:
        return None
    same = bool(situs and street and street.upper() == situs.upper())
    return {
        "owner": owner, "mailing": mailing, "situs": situs, "parcel_id": parcel_id,
        "mail_state": state,
        "absentee": (not same) if situs else None,
        "out_of_state": bool(state and state != "SC"),
        "source": "york_homestead_gis",
    }


class YorkHomestead(BaseScraper):
    slug = "counties_sc.york_homestead"
    name = "York County (SC) Homestead Exemption (Elderly/Disabled/Blind)"
    category = "motivated_seller"
    timeout_s = 180.0
    expected_min_count = 40000

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_YORK_HOMESTEAD_SOURCE", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 150000:  # hard backstop; real set ~80,600
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "ParcelID", "f": "json"}
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
                    owner = _owner(a)
                    parcel = _s(a.get("ParcelID")) or _s(a.get("TAXMAPID"))
                    if not owner or not parcel:
                        continue
                    situs = _s(a.get("PropertyAddress"))
                    land_use = _s(a.get("LandUseDesc")) or ""
                    pk = PropertyKind.SINGLE_FAMILY if "RESIDENTIAL" in land_use.upper() \
                        else PropertyKind.UNKNOWN

                    raw = {
                        "gis_exempt": {"code": "HOMESTEAD", "tag": "sc_homestead_exemption"},
                        "life_event": "elderly_disabled_homestead",
                        "tax_relief": {"kind": "homestead_exemption",
                                       "basis": "sc_homestead_age65_disabled",
                                       "deferred_value": None, "county": "York"},
                    }
                    raw["owner_mailing"] = _owner_mailing(a, owner, parcel, situs)

                    out.append(Listing(
                        source=self.slug,
                        source_url=_source_url(parcel),
                        listing_type=ListingType.ELDERLY_DISABLED,
                        property_kind=pk,
                        owner_name=owner,
                        street_address=situs,
                        state="SC",
                        county="York",
                        parcel_id=parcel,
                        market_value=_f(a.get("AprTotVal")),
                        assessed_value=_f(a.get("TaxTotVal")),
                        land_use=land_use or None,
                        acreage=_f(a.get("deededacres")),
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
