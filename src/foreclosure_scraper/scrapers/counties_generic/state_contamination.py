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
    the thinnest local coverage in the footprint and all three appear here.

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

log = structlog.get_logger()

_PAGE = 1000

#: Five-character prefixes, because that is how NC DEQ stores the county.
NC_PREFIX = ("BUNCO", "HENDE", "RUTHE", "POLK", "TRANS", "MCDOW",
             "CLEVE", "GASTO", "LINCO", "BURKE", "MITCH")
#: Full names for layers that store the county untruncated. 'Transylvanis' is a
#: real data-entry typo in the LUR registry, not a mistake here.
NC_FULL = ("BUNCOMBE", "HENDERSON", "RUTHERFORD", "POLK", "TRANSYLVANIA",
           "TRANSYLVANIS", "MCDOWELL", "CLEVELAND", "GASTON", "LINCOLN",
           "BURKE", "MITCHELL")


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


DEQ = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services"

REGISTRIES: tuple[Registry, ...] = (
    # 4,468 in-footprint. 560 have no CloseOut date, meaning the release is
    # still open and the owner is carrying an active remediation obligation.
    Registry(
        slug="nc_ust_incidents", state="NC",
        url=f"{DEQ}/Underground_Storage_Tank_Incidents/FeatureServer/0/query",
        where=_prefix("County", NC_PREFIX),
        fields=("IncidentNumber", "IncidentName", "Address", "CityTown",
                "County", "ZipCode", "DateReported", "Risk", "CurrStatus",
                "CloseOut", "LURFiled", "LUR_Resc"),
        county_field="County", situs="Address", owner="IncidentName",
        city="CityTown", zip_="ZipCode", detail="CurrStatus",
        source_page="https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks",
    ),
    # 550 in-footprint. A recorded restriction that runs with the land.
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
    # 2,086 statewide; filtered to the footprint below.
    Registry(
        slug="nc_inactive_hazardous", state="NC",
        url=f"{DEQ}/Inactive_Hazardous_Sites/FeatureServer/0/query",
        where=_prefix("SITECOUNTY", NC_PREFIX),
        fields=("EPAID", "SITENAME", "SITEADDR", "SITECITY", "SITECOUNTY",
                "Land_Use_R", "Vol_Cleanu", "SOURCE"),
        county_field="SITECOUNTY", situs="SITEADDR", owner="SITENAME",
        city="SITECITY", detail="SOURCE",
        source_page="https://www.deq.nc.gov/about/divisions/waste-management",
    ),
    # 917 in-footprint, and the only one of these that carries a full owner
    # MAILING address. A dam is a maintenance liability with a named owner.
    Registry(
        slug="nc_dam_safety", state="NC",
        url=f"{DEQ}/dam_inv_20201012/FeatureServer/0/query",
        where=_prefix("COUNTY", NC_PREFIX),
        fields=("Dam_Name", "Owner", "Owner_Type", "ADDR_LINE1", "ADDR_LINE2",
                "CITY", "STATE", "ZIP", "COUNTY", "DAM_STATUS",
                "DAM_HAZARD_POTENTIAL_DESCRIPTI"),
        county_field="COUNTY", situs_parts=("ADDR_LINE1", "ADDR_LINE2"),
        owner="Owner", city="CITY", zip_="ZIP",
        detail="DAM_HAZARD_POTENTIAL_DESCRIPTI", process="dam_liability",
        source_page="https://www.deq.nc.gov/about/divisions/energy-mineral-land-resources/dam-safety",
    ),
)


def _clean(v) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    if not s or s.upper() in ("NA", "N/A", "NONE", "NULL", "UNKNOWN"):
        return None
    return s


def _county_of(raw: str) -> Optional[str]:
    """Expand a truncated county back to its full name."""
    s = (raw or "").strip().upper()
    if not s:
        return None
    # Proper spelling matters: the scope filter and every downstream join match
    # on the county string, and "Mcdowell" from .title() does not equal
    # "McDowell". Map to the canonical form rather than title-casing.
    for full in ("Buncombe", "Henderson", "Rutherford", "Polk", "Transylvania",
                 "McDowell", "Cleveland", "Gaston", "Lincoln", "Burke",
                 "Mitchell"):
        if full.upper().startswith(s[:5]) or s.startswith(full.upper()[:5]):
            return full
    return s.title()


def _to_listing(a: dict, reg: Registry) -> Optional[Listing]:
    situs = _clean(a.get(reg.situs)) if reg.situs else None
    if not situs and reg.situs_parts:
        bits = [_clean(a.get(p)) for p in reg.situs_parts]
        situs = " ".join(b for b in bits if b) or None
    if not situs:
        return None                      # no address, no lead
    county = _county_of(str(a.get(reg.county_field) or ""))
    owner = _clean(a.get(reg.owner)) if reg.owner else None
    detail = _clean(a.get(reg.detail)) if reg.detail else None
    now = datetime.utcnow()
    return Listing(
        source=f"counties_generic.state_contamination.{reg.slug}",
        source_url=reg.source_page or reg.url,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state=reg.state, county=county,
        street_address=situs,
        city=_clean(a.get(reg.city)) if reg.city else None,
        zip_code=_clean(a.get(reg.zip_)) if reg.zip_ else None,
        owner_name=owner, defendant=owner,
        foreclosure_process=reg.process,
        description=(f"{county} {reg.state} — "
                     f"{' | '.join(x for x in (owner, situs, detail) if x)}")[:300],
        first_seen=now, last_seen=now,
        raw={"state_contamination": {"registry": reg.slug,
                                     **{k: v for k, v in a.items()
                                        if v not in (None, "")}}},
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
        guard = LayerHarvest(self.slug, [r.slug for r in REGISTRIES], attempts=3)
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
