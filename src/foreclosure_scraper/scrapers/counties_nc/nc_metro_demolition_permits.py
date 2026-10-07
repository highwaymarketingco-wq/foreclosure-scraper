"""Demolition permits in the four largest NC metros that publish them: Mecklenburg (Charlotte and
its towns), Greensboro, Durham and Cary.

SOURCES (all open, read 2026-10-07; counts are the last 730 days unless noted)
  mecklenburg  meckgis.mecklenburgcountync.gov AccelaAllPermits FeatureServer/0, 222,105 permits
               county-wide (Charlotte, Huntersville, Matthews, Cornelius, Mint Hill, ...), updated
               daily; type_of_work 'Demolition' 1,760 all-time, 1,486 issued in the window.
               owner_phone / owner_email exist on the layer and are never requested.
  greensboro   gis.greensboro-nc.gov OpenGateCity/OpenData_HRES_DS MapServer/2 (BI_Permits),
               124,985 permits; ApplicationType 'Total Demolish' 3,023 all-time, 149 in the window.
               ('Interior/Exterior Demolition', 888, is a renovation and is not read.)
  durham       webgis2.durhamnc.gov PublicServices/Inspections MapServer/10 "Demolition Permits",
               2,923 rows, 323 in the window (RESI 272). No address on the layer: PID is the
               parcel cache's key (5 of 5 sampled hit), so the situs and owner come from the join.
  cary         data.townofcary.org OpenDataSoft "permit-applications", 87,184 permits;
               'BLDG - DEMOLISH - SNGL FAM HOME (B645)' 388 + 'BLDG NON RES DEMOLITION (B649)' 54
               all-time, about 140 in the window.

WHAT A ROW MEANS
    A property with a demolition permit applied for or issued in the window (default 730 days,
    FORECLOSURE_DEMOLITION_DAYS), cancelled and withdrawn permits dropped. A demolition permit is
    the owner's (or a buyer's) application, not a city order, so it carries raw["demolition_permit"]
    and no condemned flag, as new_hanover_demolition_permits does. Owner and owner mailing are
    kept where the permit carries them (Mecklenburg, Greensboro, Cary: property-record fields).

DATELESS: no sale date; slug counties_nc.nc_metro_demolition_permits goes in
main.DATELESS_OK_SOURCES. Gate: FORECLOSURE_DEMOLITION_PERMITS=0. A dead feed fails only itself
(LayerHarvest tolerate list), never the other three.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive
from ..counties_generic._layer_kit import clean, fetch_attrs, owner_mailing

log = structlog.get_logger()

SLUG = "counties_nc.nc_metro_demolition_permits"
ENV_OFF = "FORECLOSURE_DEMOLITION_PERMITS"
ENV_DAYS = "FORECLOSURE_DEMOLITION_DAYS"

_DEAD = re.compile(r"cancel|withdraw|void|denied", re.I)   # an EXPIRED permit stays: a stalled teardown


class Feed(NamedTuple):
    name: str
    county: str
    city: Optional[str]
    url: str
    page: str
    fields: tuple[str, ...]
    m: dict                       # role -> field


FEEDS: tuple[Feed, ...] = (
    Feed("mecklenburg", "Mecklenburg", None,
         "https://meckgis.mecklenburgcountync.gov/server/rest/services/AccelaAllPermits/FeatureServer/0",
         "https://www.mecknc.gov/LUESA/CodeEnforcement",
         ("permit_number", "permit_type", "type_of_work", "permit_status", "issue_date",
          "project_address", "cama_parcel_number", "tax_jurisdiction", "zip_code",
          "owner_name", "owner_address", "owner_city", "owner_state", "owner_zip_code"),
         {"permit": "permit_number", "status": "permit_status", "date": "issue_date",
          "address": "project_address", "parcel": "cama_parcel_number", "zip": "zip_code",
          "city": "tax_jurisdiction", "owner": "owner_name",
          "mail": ("owner_address", "owner_city", "owner_state", "owner_zip_code"),
          "mail_state": "owner_state", "type": "type_of_work"}),
    Feed("greensboro", "Guilford", "Greensboro",
         "https://gis.greensboro-nc.gov/arcgis/rest/services/OpenGateCity/OpenData_HRES_DS/MapServer/2",
         "https://www.greensboro-nc.gov/departments/engineering-inspections",
         ("PermitNum", "ApplicationType", "CurrentStatus", "IssuedDate", "FinalInspectionDate",
          "FullAddress", "OwnerName", "OwnerMailAddress", "OwnerMailCity", "OwnerMailState",
          "OwnerMailZip"),
         {"permit": "PermitNum", "status": "CurrentStatus", "date": "IssuedDate",
          "address": "FullAddress", "owner": "OwnerName",
          "mail": ("OwnerMailAddress", "OwnerMailCity", "OwnerMailState", "OwnerMailZip"),
          "mail_state": "OwnerMailState", "type": "ApplicationType"}),
    Feed("durham", "Durham", "Durham",
         "https://webgis2.durhamnc.gov/server/rest/services/PublicServices/Inspections/MapServer/10",
         "https://www.durhamnc.gov/1303/Custom-Maps-and-Data-Layers",
         ("PermitNum", "PID", "ISSUE_DATE", "CO_SIGNOFF_DATE", "PROJECT_TYPE", "TYPE", "PmtStatus"),
         {"permit": "PermitNum", "status": "PmtStatus", "date": "ISSUE_DATE", "parcel": "PID",
          "type": "TYPE"}),
    Feed("cary", "Wake", "Cary",
         "https://data.townofcary.org/api/explore/v2.1/catalog/datasets/permit-applications/records",
         "https://data.townofcary.org/explore/dataset/permit-applications/",
         ("permitnum", "applieddate", "issuedate", "statuscurrent", "originaladdress1",
          "originalcity", "originalzip", "pin", "permittypedesc", "ownername", "owneraddress1",
          "ownerzip"),
         {"permit": "permitnum", "status": "statuscurrent", "date": "applieddate",
          "address": "originaladdress1", "city": "originalcity", "zip": "originalzip",
          "parcel": "pin", "owner": "ownername", "mail": ("owneraddress1", "ownerzip"),
          "type": "permittypedesc"}),
)

CARY_TYPES = ("BLDG - DEMOLISH - SNGL FAM HOME (B645)", "BLDG NON RES DEMOLITION (B649)")


def arcgis_where(feed: Feed, since: datetime) -> str:
    d = since.strftime("%Y-%m-%d")
    if feed.name == "mecklenburg":
        return f"type_of_work='Demolition' AND issue_date >= DATE '{d}'"
    if feed.name == "greensboro":
        return f"ApplicationType LIKE 'Total Demolish%' AND IssuedDate >= DATE '{d}'"
    return f"ISSUE_DATE >= DATE '{d}'"


def cary_where(since: datetime) -> str:
    types = ",".join(f'"{t}"' for t in CARY_TYPES)
    return f"permittypedesc in ({types}) and applieddate >= date'{since:%Y-%m-%d}'"


def _date(v) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _get(a: dict, feed: Feed, role: str):
    f = feed.m.get(role)
    return clean(a.get(f)) if isinstance(f, str) else None


def group_permits(feed: Feed, rows: Iterable[dict]) -> list[dict]:
    """One group per property (parcel, else address) for one feed; dead permits dropped."""
    groups: dict[str, dict] = {}
    for a in rows:
        a = drop_sensitive(a)
        if _DEAD.search(_get(a, feed, "status") or ""):
            continue
        parcel, addr = _get(a, feed, "parcel"), _get(a, feed, "address")
        key = f"p:{parcel}" if parcel else (f"a:{addr.lower()}" if addr else None)
        if not key:
            continue
        g = groups.setdefault(key, {"feed": feed, "attrs": a, "permits": []})
        g["permits"].append({"permit": _get(a, feed, "permit"), "status": _get(a, feed, "status"),
                             "type": _get(a, feed, "type"), "date": _date(a.get(feed.m["date"]))})
    for g in groups.values():
        g["permits"].sort(key=lambda p: p["date"] or datetime.min, reverse=True)
    return list(groups.values())


def to_listing(g: dict, *, now: Optional[datetime] = None) -> Listing:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    feed: Feed = g["feed"]
    a = g["attrs"]
    permits = g["permits"]
    parcel, addr = _get(a, feed, "parcel"), _get(a, feed, "address")
    owner = _get(a, feed, "owner")
    latest = permits[0]["date"].date().isoformat() if permits and permits[0]["date"] else None
    raw: dict[str, Any] = {"demolition_permit": {
        "feed": feed.name, "count": len(permits), "latest_date": latest,
        "permits": [{**p, "date": p["date"].date().isoformat() if p["date"] else None} for p in permits[:10]],
        "source": SLUG,
    }}
    if "mail" in feed.m:
        mail = owner_mailing(owner, [a.get(f) for f in feed.m["mail"]],
                             a.get(feed.m.get("mail_state") or ""), addr, parcel, "NC",
                             f"demolition_permits_{feed.name}")
        if mail:
            raw["owner_mailing"] = mail
    city = _get(a, feed, "city") or feed.city
    return Listing(
        source=SLUG,
        source_url=feed.page,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county=feed.county,
        street_address=addr,
        city=city.title() if city else None,
        zip_code=_get(a, feed, "zip"),
        parcel_id=parcel,
        owner_name=owner, defendant=owner,
        foreclosure_process="demolition_permit",
        description=(f"{feed.county} NC demolition permit{'s' if len(permits) > 1 else ''} "
                     f"({len(permits)}, latest {latest}) — {addr or parcel}")[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


async def _cary_rows(c, feed: Feed, since: datetime) -> list[dict]:
    out, offset = [], 0
    while True:
        r = await c.get(feed.url, params={"where": cary_where(since), "select": ",".join(feed.fields),
                                          "limit": 100, "offset": offset, "order_by": "permitnum"},
                        timeout=60.0)
        if r.status_code != 200:
            raise RuntimeError(f"cary: HTTP {r.status_code}")
        d = r.json()
        res = d.get("results") or []
        out.extend(res)
        offset += len(res)
        if not res or offset >= int(d.get("total_count") or 0) or offset >= 9900:
            return out


class NCMetroDemolitionPermits(BaseScraper):
    slug = SLUG
    name = "NC metro demolition permits (Mecklenburg, Greensboro, Durham, Cary)"
    category = "city_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        try:
            days = int(os.environ.get(ENV_DAYS) or 730)
        except ValueError:
            days = 730
        since = datetime.now(timezone.utc) - timedelta(days=days)
        guard = LayerHarvest(self.slug, [f.name for f in FEEDS],
                             tolerate=[f.name for f in FEEDS], attempts=2)
        out: list[Listing] = []
        async with client(timeout=60.0) as c:
            with guard:
                for feed in FEEDS:
                    rows = await guard.harvest(feed.name, self._one(c, feed, since))
                    out.extend(to_listing(g) for g in group_permits(feed, rows))
        log.info("demolition_permits.done", leads=len(out))
        return out

    @staticmethod
    def _one(c, feed: Feed, since: datetime):
        async def _run() -> list[dict]:
            if feed.name == "cary":
                return await _cary_rows(c, feed, since)
            return await fetch_attrs(c, feed.url, feed.fields, where=arcgis_where(feed, since))
        return _run
