"""Charlotte/Mecklenburg code enforcement cases — open housing/zoning
violations, a strong pre-foreclosure distress signal.

Rewritten 2026-09-15 (misc-category zero-row audit follow-up): the old
target (data.charlottenc.gov's Socrata `/resource/<id>.json` endpoints)
all 302-redirect to `hub.arcgis.com/legacy` -- the city fully migrated its
open-data portal from Socrata to ArcGIS Hub, a completely different
data-access mechanism (ArcGIS Online item search + per-dataset
FeatureServer URLs, not a flat resource ID).

Found the live replacement via the ArcGIS Online item search API
(`arcgis.com/sharing/rest/search`): "Code Enforcement Cases All"
(owner CharlotteNC, item f1c8670d7b6346ecbe17197a7316fff4), whose real
data lives at:

  https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementCasesAll/MapServer/0

Filtered to CaseStatus='Open' -- 3,341 real, currently-open cases
verified live (housing, zoning, and other code violations), including
multi-year enforcement histories with civil-penalty letters running up
to the present. `EmailAddress`/`InspectorPhone` fields exist on the
service but are deliberately NOT requested (inspector contact info, not
the property owner's -- same privacy discipline as
counties_generic/arcgis_distress_layers.py).

A second dataset was investigated for the original module's "building
permits" angle (Mecklenburg County's "Building Permit Locations" service,
worktype='Demolish') but its `issuedate`/`compldate` fields both max out
at April 2017 -- stale, not a current feed. Dropped rather than land dead
data.

PARCEL-VS-SITUS DISAGREEMENT (board audit 2026-09-23, 471 rows whose
street_address disagrees with the county parcel cache's own situs for the
same parcel_id -- see docs of that audit). Root-caused against the live
service, not guessed:

  1. FIXED HERE -- a zip-less FullAddress used to leak "CITY, NC" straight
     into street_address (see _MUNI_RE's comment): confirmed live on cases
     20200051423 and 20210033745, whose FullAddress omits the zip entirely.
  2. STRUCTURAL, NOT A BUG -- one parcel legitimately carries more than one
     addressed unit. Confirmed live on parcel 08114106: ten Housing/Nuisance
     cases spanning 2020-2026, genuinely alternating between FullAddress
     "912 Parkwood Av" and "914 Parkwood Av" for the SAME ParcelId -- a
     duplex on one tax parcel. Apartment/condo complexes are the same
     pattern at larger scale (e.g. parcel 04504206, "Wynbrook Wy" units
     #51/#60/#80 on one parcel). The parcel cache's single situs is never
     going to agree with every unit's own address; this is not fixable by
     re-parsing FullAddress differently, and it should not be re-flagged as
     a scraper bug.
  3. THE CITY'S OWN DATA, NOT OURS -- ParcelId and FullAddress sometimes
     disagree with each other on the SAME case, confirmed live. Case
     20220013172: FullAddress "9013 Moores Chapel Rd", but ParcelId
     05512204's own situs in the county parcel layer is "1234 Kiker Cr" (a
     different street; the parcel's owner-mailing address happens to be
     "9023 Moores Chapel Rd", ten off from the case's own address -- most
     likely the city's case-management system resolved the ParcelId off the
     owner's mailing address rather than the violation site). We relay
     FullAddress and ParcelId exactly as gis.charlottenc.gov reports them
     for that case; there is no better field on the service to prefer.

Free, public, no login.
Slug: city_websites.charlotte_open_data
Category: city
ListingType: DISTRESSED
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SERVICE_URL = (
    "https://gis.charlottenc.gov/arcgis/rest/services/HNS/"
    "CodeEnforcementCasesAll/MapServer/0/query"
)
FIELDS = (
    "CaseNumber,ParcelId,CaseType,FullAddress,CaseStatus,"
    "DateCreated,CouncilDistrict,DetailedDescription"
)
_PAGE = 2000

# "2601 ABELWOOD RD CHARLOTTE, NC 28216" -- no delimiter between street and
# city, so a generic split can't tell them apart (a lazy regex would just
# grab the house number as "street"). Anchor on the known Mecklenburg
# municipality names that appear before ", NC <zip>" instead.
_MUNICIPALITIES = (
    "CHARLOTTE", "HUNTERSVILLE", "CORNELIUS", "DAVIDSON", "MATTHEWS",
    "MINT HILL", "PINEVILLE", "STALLINGS",
)
_ZIP_RE = re.compile(r",\s*NC\s+(\d{5})", re.I)
# The zip group is OPTIONAL. Confirmed live against the source service
# (gis.charlottenc.gov, CodeEnforcementCasesAll) that FullAddress sometimes
# omits the zip entirely, e.g. case 20200051423 (parcel 03505220):
#     FullAddress = "OAK ST CHARLOTTE, NC "
# and case 20210033745 (parcel 16914128):
#     FullAddress = "435 GRIFFITH RD CHARLOTTE, NC "
# When _MUNI_RE required a trailing 5-digit zip, neither it nor _ZIP_RE
# matched either string, so _parse_address fell through to its last-resort
# branch and returned the WHOLE raw string -- "CHARLOTTE, NC" included -- as
# street_address. Board audit 2026-09-23 caught this live: street_address
# "OAK ST CHARLOTTE, NC" and "435 GRIFFITH RD CHARLOTTE, NC" both had the
# city/state baked into the address field instead of stripped out.
_MUNI_RE = re.compile(
    r"\b(" + "|".join(_MUNICIPALITIES) + r")\s*,?\s*NC\b(?:\s+\d{5})?", re.I
)
# A house-number-less street ("OAK ST" once "CHARLOTTE, NC" is stripped off
# the zip-less case above) isn't independently locatable -- it can't be
# matched to a specific parcel or targeted as a lead. Require a leading
# house number, same bar resolve_parcel_from_address.py holds addresses to
# ("the lead's street must be ONE numbered address").
_HOUSE_NUM_RE = re.compile(r"^\d")


def _usable_street(street: str | None) -> str | None:
    if street and _HOUSE_NUM_RE.match(street):
        return street
    return None


def _parse_address(full: str) -> tuple[str | None, str | None, str | None]:
    full = (full or "").strip()
    zip_m = _ZIP_RE.search(full)
    zip_code = zip_m.group(1) if zip_m else None

    muni_m = _MUNI_RE.search(full)
    if muni_m:
        street = full[: muni_m.start()].strip().rstrip(",")
        city = muni_m.group(1).title()
        return _usable_street(street), city, zip_code

    # Unknown municipality: fall back to everything before the zip as the
    # street (better than a wrong city split).
    if zip_m:
        street = full[: zip_m.start()].strip().rstrip(",")
        return _usable_street(street), None, zip_code
    return _usable_street(full), None, None


def _to_listing(attrs: dict) -> Listing | None:
    case_num = attrs.get("CaseNumber")
    full_addr = attrs.get("FullAddress")
    if not case_num or not full_addr:
        return None

    street, city, zip_code = _parse_address(full_addr)
    if not street:
        return None

    created_ms = attrs.get("DateCreated")
    created = datetime.utcfromtimestamp(created_ms / 1000) if created_ms else None

    desc = (attrs.get("DetailedDescription") or "").replace("\r\n", " ")[:400]
    case_type = attrs.get("CaseType") or "Code Enforcement"

    return Listing(
        source="city_websites.charlotte_open_data",
        source_url=f"https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementCasesAll/MapServer/0/{case_num}",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street,
        city=city or "Charlotte",
        state="NC",
        county="Mecklenburg",
        zip_code=zip_code,
        parcel_id=(attrs.get("ParcelId") or "").strip() or None,
        case_number=str(case_num),
        description=f"Charlotte code enforcement — {case_type}: {desc}"[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"charlotte_code_enforcement": {
            "case_type": case_type,
            "case_status": attrs.get("CaseStatus"),
            "council_district": attrs.get("CouncilDistrict"),
            "date_created": created.isoformat() if created else None,
        }},
    )


class CharlotteOpenData(BaseScraper):
    slug = "city_websites.charlotte_open_data"
    name = "Charlotte/Mecklenburg Open Code Enforcement Cases"
    category = "city"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        offset = 0
        try:
            async with client(timeout=30.0) as c:
                while True:
                    r = await c.get(SERVICE_URL, params={
                        "where": "CaseStatus='Open'",
                        "outFields": FIELDS,
                        "resultOffset": offset,
                        "resultRecordCount": _PAGE,
                        "f": "json",
                    }, timeout=30.0)
                    if r.status_code != 200:
                        log.warning("charlotte.http_error", status=r.status_code)
                        break
                    data = r.json()
                    if "error" in data:
                        log.warning("charlotte.api_error", error=str(data["error"])[:200])
                        break
                    feats = data.get("features") or []
                    for f in feats:
                        li = _to_listing(f.get("attributes") or {})
                        if li:
                            out.append(li)
                    if len(feats) < _PAGE or not data.get("exceededTransferLimit"):
                        break
                    offset += _PAGE
        except Exception as exc:
            log.warning("charlotte.fetch_fail", error=str(exc)[:160])

        log.info("charlotte.fetch_done", count=len(out))
        return out
