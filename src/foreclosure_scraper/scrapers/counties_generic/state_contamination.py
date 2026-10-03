"""State and federal contamination registries — properties the government has
already recorded as impaired.

WHY THIS IS A DISTRESS SIGNAL, not a directory
    A property with a confirmed petroleum release, a recorded land-use
    restriction, or a listing on the inactive-hazardous inventory is genuinely
    hard to sell. Lenders balk, buyers walk, and the owner is often carrying an
    open remediation obligation. That is motivation, and it is recorded in
    public state registries nobody in this engine was reading.

WHY STATEWIDE SOURCES MATTER MOST HERE
    These files cover every county in one fetch, which is exactly what the
    counties that publish nothing locally need. Mitchell, Polk and McDowell have
    the thinnest local coverage in the old 18-county flip footprint and all
    three appear here.

    SCOPE (fixed 2026-10-03): the WHERE clauses below used to filter server-side
    down to that same 11-county NC footprint, even though every one of these
    queries already pulls NC statewide in a single paginated fetch -- the
    filter cost nothing to remove and was silently discarding real
    contamination rows in the other 89 NC counties before they were ever
    fetched. The 2026-09-15 in_scope_distressed mandate ("if its a distressed
    property its anywhere in nc and sc") makes every NC county admissible for
    this generic DISTRESSED-type lead, so NC_PREFIX/NC_FULL now cover all 100
    real NC counties (validation.py), not just the flip footprint.

THE COUNTY COLUMN IS TRUNCATED — the trap that hides 89% of the rows
    NC DEQ's UST incident file stores County truncated to FIVE characters:
    'BUNCO', 'HENDE', 'TRANS', 'RUTHE'. An exact-match IN() over full county
    names returns 481 rows. Prefix matching returns 4,468 — the same data, 9x
    more of it. Verified by grouping the column and counting.

    NC DEQ's LUR registry has a different defect: a data-entry typo spells
    Transylvania as 'Transylvanis' on two Ecusta Mill records, both of which
    carry usable deed references. The county list below includes the typo.

PRIVACY
    These carry owner-adjacent PII despite looking industrial. Prj_Name on the
    LUR registry is frequently a named private individual at a residential
    address ('Joe D Huskins Estate' at 679 Ridge Road, Spruce Pine). That is
    the same class of exposure as the recorded deed it derives from, so it is
    defensible to ingest — but it is not "no personal data", and it is logged
    as owner-adjacent rather than pretended away.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind
from ...validation import NC_COUNTIES as _NC_COUNTY_NAMES

log = structlog.get_logger()

_PAGE = 1000

#: Five-character prefixes, because that is how NC DEQ stores the county.
#: Widened 2026-10-03 from the 18-county (11-NC) flip footprint to all 100
#: real NC counties. These are single statewide ArcGIS FeatureServer queries
#: either way (one POST, paginated by offset) -- the old 11-county WHERE
#: filter was not saving any fetch cost, it was discarding real contamination
#: rows in the other 89 NC counties server-side before they ever reached this
#: scraper. The 2026-09-15 in_scope_distressed mandate ("if its a distressed
#: property its anywhere in nc and sc") makes every one of those rows
#: admissible for this generic DISTRESSED-type lead; the footprint-only
#: filter here was simply never revisited after that mandate, the same bug
#: class 2026-10-03's comps fix closed for enrichment_comps.py. Verified
#: programmatically: none of the 100 real NC county names (validation.py)
#: share the same first 5 characters once spaces are stripped, so a flat
#: prefix map has no collision risk.
NC_PREFIX = tuple(sorted({c.upper().replace(" ", "")[:5] for c in _NC_COUNTY_NAMES}))
#: Full names for layers that store the county untruncated. 'TRANSYLVANIS' is a
#: real data-entry typo in the LUR registry, not a mistake here.
NC_FULL = tuple(sorted({c.upper() for c in _NC_COUNTY_NAMES} | {"TRANSYLVANIS"}))


def _in(col: str, vals: Iterable[str]) -> str:
    return f"UPPER({col}) IN (" + ",".join(f"'{v}'" for v in vals) + ")"


def _prefix(col: str, prefixes: Iterable[str]) -> str:
    return " OR ".join(f"UPPER({col}) LIKE '{p}%'" for p in prefixes)


class Registry(NamedTuple):
    slug: str
    state: str
    url: str
    where: str
    fields: tuple[str, ...]
    county_field: str
    situs: Optional[str] = None
    situs_parts: tuple[str, ...] = ()
    owner: Optional[str] = None
    city: Optional[str] = None
    zip_: Optional[str] = None
    detail: Optional[str] = None
    process: str = "contamination"
    source_page: str = ""
    # lat_field/lon_field: the layer's OWN authoritative coordinate for the thing being
    # inventoried (not a geocode of some address field). When set, this is used directly
    # as Listing.latitude/longitude instead of leaving the row for the Census-geocode
    # backfill to place from street_address -- see nc_dam_safety below for why that
    # backfill is actively wrong for this registry.
    lat_field: Optional[str] = None
    lon_field: Optional[str] = None
    # id_field: a real per-record identifier (independent of any address) to key
    # parcel_id/dedupe on, for a registry where situs is not an address field.
    id_field: Optional[str] = None
    # mailing_fields: fields that are the OWNER'S MAILING address, not the site/situs
    # location of the thing this row is about. Never fed into street_address/city/
    # zip_code (which the geocode backfill treats as the property's location) --
    # stashed under raw['state_contamination']['owner_mailing'] for contact purposes only.
    mailing_fields: tuple[str, ...] = ()


DEQ = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services"

REGISTRIES: tuple[Registry, ...] = (
    # 4,468 rows in the old 11-county footprint (now widened statewide,
    # 2026-10-03). 560 have no CloseOut date, meaning the release is
    # still open and the owner is carrying an active remediation obligation.
    #
    # LatDec/LongDec/DocsLink/DateOccurred/LUR_State verified live 2026-10-01
    # (field list + sample rows pulled directly from the FeatureServer):
    # LatDec/LongDec are the layer's OWN authoritative coordinate for the
    # tank site, not a geocode of Address -- same "use the registry's own
    # coordinate, don't trust the downstream geocode backfill" fix already
    # applied to nc_dam_safety below. DocsLink is a real, free, no-login NC
    # DEQ edocs (Laserfiche) search link scoped to this incident's own
    # Program_ID -- a working document-search entry point this scraper was
    # dropping entirely (confirmed live: HTTP 302, resolves).
    Registry(
        slug="nc_ust_incidents", state="NC",
        url=f"{DEQ}/Underground_Storage_Tank_Incidents/FeatureServer/0/query",
        where=_prefix("County", NC_PREFIX),
        fields=("IncidentNumber", "IncidentName", "Address", "CityTown",
                "County", "ZipCode", "DateReported", "DateOccurred", "Risk",
                "CurrStatus", "CloseOut", "LURFiled", "LUR_Resc", "LUR_State",
                "LatDec", "LongDec", "DocsLink"),
        county_field="County", situs="Address", owner="IncidentName",
        city="CityTown", zip_="ZipCode", detail="CurrStatus",
        lat_field="LatDec", lon_field="LongDec",
        source_page="https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks",
    ),
    # 550 rows in the old 11-county footprint (now widened statewide,
    # 2026-10-03). A recorded restriction that runs with the land.
    Registry(
        slug="nc_land_use_restrictions", state="NC",
        url=f"{DEQ}/NoticeLUR_View/FeatureServer/0/query",
        where=_in("Prj_County", NC_FULL),
        fields=("Prj_Number", "Prj_Name", "Prj_Address", "Prj_City",
                "Prj_County", "DWM_Program", "Instrument", "Instrument_Status",
                "Deed_Bk", "Deed_Pg", "Deed_Rec_Date", "Allowed_Use"),
        county_field="Prj_County", situs="Prj_Address", owner="Prj_Name",
        city="Prj_City", detail="DWM_Program",
        source_page="https://www.deq.nc.gov/about/divisions/waste-management",
    ),
    # 2,086 statewide (no longer filtered down to the old footprint below,
    # see SCOPE note in the module docstring).
    #
    # LATITUDE/LONGITUDE/Laserfiche verified live 2026-10-01, same pattern as
    # nc_ust_incidents above: LATITUDE/LONGITUDE is the layer's own
    # authoritative site coordinate (not a geocode of SITEADDR, which is
    # frequently a state-road description like "SR 3495-GLENN BRIDGE RD"
    # that a geocoder would struggle with anyway), and Laserfiche is a real
    # per-site NC DEQ edocs document-search link (e.g. the PFAS site at 180
    # Erwin Hills Rd, Buncombe) that was never being captured.
    Registry(
        slug="nc_inactive_hazardous", state="NC",
        url=f"{DEQ}/Inactive_Hazardous_Sites/FeatureServer/0/query",
        where=_prefix("SITECOUNTY", NC_PREFIX),
        fields=("EPAID", "SITENAME", "SITEADDR", "SITECITY", "SITECOUNTY",
                "Land_Use_R", "Vol_Cleanu", "SOURCE", "LATITUDE", "LONGITUDE",
                "Laserfiche"),
        county_field="SITECOUNTY", situs="SITEADDR", owner="SITENAME",
        city="SITECITY", detail="SOURCE",
        lat_field="LATITUDE", lon_field="LONGITUDE",
        source_page="https://www.deq.nc.gov/about/divisions/waste-management",
    ),
    # 917 rows in the old 11-county footprint (now widened statewide,
    # 2026-10-03). ADDR_LINE1/2 + CITY/STATE/ZIP are the DAM OWNER'S MAILING
    # address, not the dam's location -- confirmed 2026-09-30: "Betty Kay Lake Dam"
    # (Transylvania County) has ADDR_LINE1/CITY = "417 Clairemont Avenue" / "Decatur, GA"
    # (the property-owners-association's mailing address) while its own LATITUDE/
    # LONGITUDE field correctly sits in Transylvania County, NC. A prior version of this
    # registry fed the mailing block into situs_parts, so the Census-geocode backfill
    # geocoded the OWNER's out-of-state street and stamped it on the dam's row as its
    # location -- e.g. that same "Cascade Lake Dam" landed 500+ miles away in Atlanta,
    # GA despite county correctly reading "Transylvania" the whole time. This is what
    # 2026-09-30's >50mi-from-county-seat audit found driving ~15% of Transylvania's
    # (and a smaller share of Burke/Lincoln/Buncombe/Polk/Cleveland/McDowell/Mitchell's)
    # census-geocoded rows: a wrong-field bug, not a mislabeled county.
    # Fix: this layer ALSO publishes the dam's own LATITUDE/LONGITUDE (confirmed via the
    # FeatureServer's field list) and a real per-dam id (NID_ID) -- use those directly
    # instead of ever geocoding the mailing address. The mailing block still has value
    # (who to contact about the liability) so it is kept, but under raw.owner_mailing,
    # never as street_address/city/zip_code.
    # Phone/NOD_DATE/DSO_DATE verified live 2026-10-01: Phone is a real,
    # frequently-populated contact number for the dam owner -- including
    # individuals, not just HOAs/companies (e.g. "Jane Shuttleworth", Mother
    # Earth Dam, a personal phone number) -- and was being dropped entirely
    # despite contactability being this engine's #1 ceiling. NOD_DATE/
    # DSO_DATE (Notice of Deficiency / Dam Safety Order dates) are a real
    # open-enforcement severity signal when populated (confirmed live on
    # Mother Earth Dam Lower, Transylvania County, NOD_DATE 03/04/2024).
    Registry(
        slug="nc_dam_safety", state="NC",
        url=f"{DEQ}/dam_inv_20201012/FeatureServer/0/query",
        where=_prefix("COUNTY", NC_PREFIX),
        fields=("Dam_Name", "Owner", "Owner_Type", "ADDR_LINE1", "ADDR_LINE2",
                "CITY", "STATE", "ZIP", "Phone", "COUNTY", "DAM_STATUS",
                "NID_ID", "LATITUDE", "LONGITUDE", "NOD_DATE", "DSO_DATE",
                "DAM_HAZARD_POTENTIAL_DESCRIPTI"),
        county_field="COUNTY",
        owner="Owner",
        lat_field="LATITUDE", lon_field="LONGITUDE", id_field="NID_ID",
        mailing_fields=("ADDR_LINE1", "ADDR_LINE2", "CITY", "STATE", "ZIP", "Phone"),
        detail="DAM_HAZARD_POTENTIAL_DESCRIPTI", process="dam_liability",
        source_page="https://www.deq.nc.gov/about/divisions/energy-mineral-land-resources/dam-safety",
    ),
)


def _clean(v) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    if not s or s.upper() in ("NA", "N/A", "NONE", "NULL", "UNKNOWN"):
        return None
    return s


#: raw (5-char truncated) -> canonical name, for every real NC county.
_NC_PREFIX_MAP: dict[str, str] = {
    c.upper().replace(" ", "")[:5]: c for c in _NC_COUNTY_NAMES
}
#: raw (untruncated) -> canonical name, including the LUR typo.
_NC_FULL_MAP: dict[str, str] = {c.upper(): c for c in _NC_COUNTY_NAMES}
_NC_FULL_MAP["TRANSYLVANIS"] = "Transylvania"


def _county_of(raw: str) -> Optional[str]:
    """Expand a truncated (or untruncated) county back to its canonical name."""
    s = (raw or "").strip().upper()
    if not s:
        return None
    # Proper spelling matters: the scope filter and every downstream join match
    # on the county string, and "Mcdowell" from .title() does not equal
    # "McDowell". Map to the canonical form rather than title-casing.
    exact = _NC_FULL_MAP.get(s)
    if exact:
        return exact
    prefix = _NC_PREFIX_MAP.get(s.replace(" ", "")[:5])
    if prefix:
        return prefix
    return s.title()


def _coord(a: dict, field: Optional[str]) -> Optional[float]:
    """Pull a lat/lon value from the layer's own coordinate field, not a geocode.
    Rejects exactly 0.0 (this source's null-placeholder, not a real "null island"
    coordinate in our NC/SC footprint) and non-numeric values. Proper per-axis
    range bounds are applied by the caller, which knows which axis this is."""
    if not field:
        return None
    try:
        v = float(a.get(field))
    except (TypeError, ValueError):
        return None
    return v if v != 0.0 else None


def _to_listing(a: dict, reg: Registry) -> Optional[Listing]:
    situs = _clean(a.get(reg.situs)) if reg.situs else None
    if not situs and reg.situs_parts:
        bits = [_clean(a.get(p)) for p in reg.situs_parts]
        situs = " ".join(b for b in bits if b) or None

    lat = _coord(a, reg.lat_field)
    lon = _coord(a, reg.lon_field)
    if lat is not None and not (-90.0 <= lat <= 90.0):
        lat = None
    if lon is not None and not (-180.0 <= lon <= 180.0):
        lon = None
    record_id = _clean(a.get(reg.id_field)) if reg.id_field else None

    if not situs and lat is None and not record_id:
        return None                      # no address, no coordinate, no id -- no lead

    county = _county_of(str(a.get(reg.county_field) or ""))
    owner = _clean(a.get(reg.owner)) if reg.owner else None
    detail = _clean(a.get(reg.detail)) if reg.detail else None
    now = datetime.utcnow()

    desc = f"{county} {reg.state} — {' | '.join(x for x in (owner, situs, detail) if x)}"
    mailing = None
    if reg.mailing_fields:
        block = {f: _clean(a.get(f)) for f in reg.mailing_fields}
        block = {k: v for k, v in block.items() if v}
        if block:
            mailing = block
            if not situs:
                # No real site address exists in this layer -- say so explicitly so an
                # operator (or a future scraper edit) never mistakes the mailing block
                # in raw for this row's location the way street_address used to.
                desc += " (location from registry coordinates; contact address is owner mailing, in raw)"

    raw_extra: dict = {"registry": reg.slug}
    if mailing:
        raw_extra["owner_mailing"] = mailing
    raw_extra.update({k: v for k, v in a.items() if v not in (None, "")})

    return Listing(
        source=f"counties_generic.state_contamination.{reg.slug}",
        source_url=reg.source_page or reg.url,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state=reg.state, county=county,
        street_address=situs,
        city=_clean(a.get(reg.city)) if reg.city else None,
        zip_code=_clean(a.get(reg.zip_)) if reg.zip_ else None,
        latitude=lat, longitude=lon,
        parcel_id=record_id,
        owner_name=owner, defendant=owner,
        foreclosure_process=reg.process,
        description=desc[:300],
        first_seen=now, last_seen=now,
        raw={"state_contamination": raw_extra},
    )


async def _fetch(c, reg: Registry) -> list[Listing]:
    out: list[Listing] = []
    offset = 0
    while True:
        r = await c.post(reg.url, data={
            "where": reg.where, "outFields": ",".join(reg.fields),
            "returnGeometry": "false", "resultOffset": offset,
            "resultRecordCount": _PAGE, "orderByFields": reg.fields[0],
            "f": "json",
        }, timeout=90.0)
        if r.status_code != 200:
            raise RuntimeError(f"{reg.slug}: HTTP {r.status_code}")
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"{reg.slug}: {str(d['error'])[:120]}")
        feats = d.get("features") or []
        for f in feats:
            li = _to_listing(f.get("attributes") or {}, reg)
            if li:
                out.append(li)
        if len(feats) < _PAGE or not d.get("exceededTransferLimit"):
            break
        offset += _PAGE
    log.info("state_contamination.registry_done", registry=reg.slug, leads=len(out))
    return out


class StateContamination(BaseScraper):
    slug = "counties_generic.state_contamination"
    name = "State contamination registries (NC DEQ UST / LUR / hazardous / dams)"
    category = "state_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_STATE_CONTAMINATION") == "0":
            return []
        out: list[Listing] = []
        # nc_land_use_restrictions layer now returns {'code': 499, 'message':
        # 'Token Required'} (verified 2026-09-15) -- NC DEQ's ArcGIS server
        # added an auth requirement this project has no free/public token
        # for (not the "intermittent 500s" this comment used to describe;
        # updated to match observed behavior). Tolerate its failure so the
        # other 3 live registries still ship their 5,000+ rows instead of
        # being discarded by PartialHarvest.
        guard = LayerHarvest(
            self.slug, [r.slug for r in REGISTRIES],
            tolerate={"nc_land_use_restrictions"}, attempts=3,
        )
        async with client(timeout=90.0) as c:
            with guard:
                for reg in REGISTRIES:
                    out.extend(await guard.harvest(reg.slug, self._one(c, reg)))
        return out

    @staticmethod
    def _one(c, reg: Registry):
        async def _run() -> list[Listing]:
            return await _fetch(c, reg)
        return _run
