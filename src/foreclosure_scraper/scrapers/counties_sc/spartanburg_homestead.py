"""Spartanburg County SC homestead exemption (elderly/disabled/blind) -- a PROPERTY-KEYED
motivated-seller source, the SC analog of counties_nc.buncombe_elderly.py and the third SC
county (after York, Lexington) whose CAMA layer carries this flag cleanly.

SC Code 12-37-250 excludes the first $50,000 of a legal residence's fair market value for an
owner who is 65+, totally and permanently disabled, or legally blind. Spartanburg's own CAMA
parcel layer carries this as a per-parcel HomesteadNumber flag. Those owners are prime
motivated-seller prospects for the same reason Buncombe's/York's/Lexington's elderly/disabled
homeowners are (downsizing, can't maintain, heirs about to inherit) -- unlike a name-indexed
lane, this is property-keyed: one bulk query returns owner + address + value + parcel, a
complete lead, no name resolution.

CORRECTS A STALE FINDING. enrichment_tax_relief.py's own module docstring (2026-08-06 pass)
says "Spartanburg HomesteadNumber has 32 non-empty values that look like book codes" and
concluded the field was not a usable personal exemption flag. Live-reconfirmed 2026-11-16: that
read was incomplete, not wrong about the codes it saw -- HomesteadNumber DOES carry ~14 tiny
book-code-shaped values (A2/A3/A4, B1A/B1D/B2B/B11A/B11E/B16A/B16B/B16C/B31, each under 90 rows,
total under 200 parcels; likely a tax-map/exemption-APPLICATION-book reference, unexplained but
irrelevant here) -- but ALONGSIDE those, HomesteadNumber='H' is a SEPARATE, massive, clean
population: 31,265 of ~370,000 parcels countywide (groupByFieldsForStatistics count, live
2026-11-16), every sampled row an individual-named owner (never an institution), matching the
identical shape of York's HOMESTEAD='Y' and Lexington's Homestead='YES'. Whatever produced the
2026-08-06 "32 codes" read evidently never surfaced 'H' itself (sorted distinctly it sits between
'B31' and nothing else alphabetically-after, so a naive first-N-distinct-values sample should
have caught it -- most likely that pass sampled raw ROWS rather than distinct values, or read a
narrower county_records_matrix.json-era snapshot of the layer that predates 'H' use at this
volume). This file's own live counts supersede that note; do not re-decline this field.

THIS IS NOT A DUPLICATE OF enrichment_tax_relief.py. That module only has entries for
Buncombe/Henderson/Burke/Lincoln/Gaston/Rutherford/York/Lexington; it does not query Spartanburg
at all today. If a Spartanburg entry is later added there (to also tag existing non-homestead-
sourced board rows via the senior_exemption distress signal), this scraper's own rows already
satisfy that module's "skip if already tagged" guard (raw['tax_relief'] is pre-populated below,
in the exact "homestead_exemption"/"sc_homestead_age65_disabled" shape enrichment_tax_relief's
`_classify()` york_sc/lexington_sc paths produce) -- no scoring change would be needed. This is
the full-county BULK SWEEP (every one of the ~31,265 homesteaded parcels becomes its own lead,
same as York/Lexington/Buncombe), which is the only way the homesteaded owners who carry no
OTHER distress signal ever reach the board at all.

ENDPOINT (free, anonymous, no auth/captcha/paywall -- live-verified 2026-11-16):
  https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query
  WHERE HomesteadNumber='H' -> 31,265 live parcels. maxRecordCount 2000 (live-verified), so the
  same offset-paging shape as buncombe_elderly.py/york_homestead.py is required.

GISParcelNumber CAN BE BLANK (live-verified: the first HomesteadNumber='H' row sorted by
GISParcelNumber has GISParcelNumber=''). MAPNUMBER ("7-18-02-017.00" shape) is always populated
on every sampled row and is the fallback, same two-tier shape as York's ParcelID-or-TAXMAPID.
PARCELNUMBER ("17") is only the card/sub-id within one MAPNUMBER, not unique countywide, and is
not used as the identifier.

THREE VALUE TIERS, NOT TWO. Unlike York/Lexington (Appraised + one post-ratio "Tax" value),
this layer publishes Appraised (fair market), Taxable (an intermediate, CAMA-internal basis --
live sample ~84% of appraised; not documented further and not used here) and Assessed (the
actual 4%/6%-ratio value used for the tax bill, roughly Taxable x the AssessmentCode ratio).
market_value reads Appraised; assessed_value reads Assessed (the smallest, tax-bill-facing
number -- the same convention market_value/assessed_value carry on every other scraper in this
project). Taxable is deliberately not surfaced: inventing a meaning for an undocumented
middle tier would be worse than omitting it.

NO SEPARATE MAILING ADDRESS ON THIS LAYER (live field-schema check, 2026-11-16, 99 fields: no
Mail*/Taxpayer-address columns distinct from the parcel's own StreetAddress/City/Zip). Unlike
York/Lexington, owner_mailing is not constructed here -- for a homesteaded (legal-residence)
parcel the situs IS the mailing address by statute in the overwhelming case, and fabricating a
separate mailing block from the same three columns the situs already uses would be a no-op that
could misleadingly imply a second, independently-sourced address existed.

AN 'H' ROW CAN CARRY A NON-4% AssessmentCode (live-sampled: '6% RES VAC M' on a vacant-lot/
mobile-home-lot parcel with HomesteadNumber='H'). That is the county's own on-file combination,
not a parse error -- it is reported as-is (AssessmentCode kept in raw['gis_exempt'] as
corroborating evidence only); whether a lapsed/reclassified homestead flag should still count is
a scoring/verification decision, not this scraper's to make (same discipline buncombe_elderly.py
and york_homestead.py already apply to their own county's data oddities).

Gate with FORECLOSURE_SPARTANBURG_HOMESTEAD_SOURCE=0 to skip.
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

QUERY_URL = "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query"
_WHERE = "HomesteadNumber='H'"
_OUT = ("GISParcelNumber,MAPNUMBER,OwnerName,TaxpayerName,StreetAddress,City,State,Zip,"
        "CurrentAppraisedLandValue,CurrentAppraisedBuildingValue,CurrentAssessedLandValue,"
        "CurrentAssessedBuildingValue,LandUse,Acreage,SaleDate,SaleAmount,AssessmentCode,"
        "HomesteadNumber")
_PAGE = 2000  # the layer's own maxRecordCount (live-verified 2026-11-16)


def _source_url(parcel_id: str) -> str:
    where = f"GISParcelNumber%3D%27{parcel_id}%27+OR+MAPNUMBER%3D%27{parcel_id}%27"
    return f"{QUERY_URL}?where={where}&outFields=*&f=html"


def _s(v) -> str | None:
    return str(v).strip() or None if v not in (None, "") else None


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _money_sum(a: dict, land_field: str, bldg_field: str) -> float | None:
    land, bldg = _f(a.get(land_field)), _f(a.get(bldg_field))
    total = (land or 0.0) + (bldg or 0.0)
    return total if total > 0 else None


def _iso_date_ms(v) -> str | None:
    """Esri date (epoch milliseconds) -> 'YYYY-MM-DD'. Guards the FoxPro/dBase-style
    1900-01-01 sentinel (-2208988800000) and other pre-1950 placeholder dates, the same
    discipline buncombe_elderly.py applies to its own 8-digit DeedDate strings."""
    try:
        ms = int(v)
    except (TypeError, ValueError):
        return None
    try:
        d = datetime.utcfromtimestamp(ms / 1000.0)
    except (OverflowError, OSError, ValueError):
        return None
    return d.date().isoformat() if d.year >= 1950 else None


def _owner(a: dict) -> str | None:
    return _s(a.get("OwnerName")) or _s(a.get("TaxpayerName"))


class SpartanburgHomestead(BaseScraper):
    slug = "counties_sc.spartanburg_homestead"
    name = "Spartanburg County (SC) Homestead Exemption (Elderly/Disabled/Blind)"
    category = "motivated_seller"
    timeout_s = 180.0
    expected_min_count = 15000

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_SPARTANBURG_HOMESTEAD_SOURCE", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 60000:  # hard backstop; real set ~31,265
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "GISParcelNumber", "f": "json"}
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
                    parcel = _s(a.get("GISParcelNumber")) or _s(a.get("MAPNUMBER"))
                    if not owner or not parcel:
                        continue
                    situs = _s(a.get("StreetAddress"))
                    city = _s(a.get("City"))
                    land_use = _s(a.get("LandUse")) or ""
                    pk = PropertyKind.SINGLE_FAMILY if "RESIDENTIAL" in land_use.upper() \
                        else PropertyKind.UNKNOWN

                    raw: dict = {
                        "gis_exempt": {"code": "H", "tag": "sc_homestead_exemption"},
                        "life_event": "elderly_disabled_homestead",
                        "tax_relief": {"kind": "homestead_exemption",
                                       "basis": "sc_homestead_age65_disabled",
                                       "deferred_value": None, "county": "Spartanburg"},
                    }
                    assess_code = _s(a.get("AssessmentCode"))
                    if assess_code:
                        raw["gis_exempt"]["assessment_code"] = assess_code
                    sale_amt = _f(a.get("SaleAmount"))
                    sale_date = _iso_date_ms(a.get("SaleDate"))
                    if sale_amt and sale_date:
                        raw["gis"] = {"last_sale": {"date": sale_date, "amount": sale_amt,
                                                     "source": "spartanburg_homestead_gis"}}

                    out.append(Listing(
                        source=self.slug,
                        source_url=_source_url(parcel),
                        listing_type=ListingType.ELDERLY_DISABLED,
                        property_kind=pk,
                        owner_name=owner,
                        street_address=situs,
                        city=(city.title() if city else None),
                        state="SC",
                        county="Spartanburg",
                        zip_code=_s(a.get("Zip")),
                        parcel_id=parcel,
                        market_value=_money_sum(a, "CurrentAppraisedLandValue",
                                                "CurrentAppraisedBuildingValue"),
                        assessed_value=_money_sum(a, "CurrentAssessedLandValue",
                                                  "CurrentAssessedBuildingValue"),
                        land_use=land_use or None,
                        acreage=_f(a.get("Acreage")),
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
