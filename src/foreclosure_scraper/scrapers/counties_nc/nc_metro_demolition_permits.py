"""Demolition permits in the four largest NC metros that publish them: Mecklenburg (Charlotte and
its towns), Greensboro, Durham and Cary.

SOURCES (Greensboro/Durham/Cary read live 2026-10-07; Mecklenburg RE-VERIFIED 2026-10-14 after its
GIS backend moved -- see the dated note below. Counts are ALL-TIME now; the 730-day window that
used to gate the fetch itself is gone, see "DATE COVERAGE" below)
  mecklenburg  meckgis.mecklenburgcountync.gov BuildingPermits FeatureServer/0, 482,384 permits
               county-wide (Charlotte, Huntersville, Matthews, Cornelius, Mint Hill, ...), updated
               daily. 2026-10-14: the old `AccelaAllPermits` service and all its field names
               (`type_of_work`, `issue_date`, `permit_number`, `project_address`, `owner_name`,
               `owner_address`, ...) are GONE -- a straight 404, not a date problem -- replaced by
               this `BuildingPermits` service with an unrelated field schema (`worktype`,
               `issuedate`, `permitnum`, `projadd`, `ownname`, ...). Worse, the county's OWN
               classification of "this is a demolition permit" changed shape at the same time it
               must have migrated: `worktype='Demolish'` is a LEGACY tag used only through
               2017-03-09 (8,591 rows, 1991-2017); every demolition since then is tagged with an
               empty worktype and is only identifiable by `permitdesc LIKE '%Demolish/Move Off%'`
               (5,401 rows, 2017-04 to present, continuous through today). The two patterns barely
               overlap in time, so the WHERE clause now OR's them: 13,992 matching rows all-time
               (vs. 0 before this fix -- the dead URL meant this feed returned nothing at all,
               LayerHarvest's tolerate list silently absorbing the 404 every run). No owner-mailing
               STREET field survives the migration (owncity/ownstate/ownzipcode do; no street-line
               field exists on the new schema), so Mecklenburg's owner_mailing block is now
               city/state/zip only, never a full street line -- a real but unavoidable data-quality
               step down, not something this fix can restore.
  greensboro   gis.greensboro-nc.gov OpenGateCity/OpenData_HRES_DS MapServer/2 (BI_Permits),
               124,985 permits; ApplicationType 'Total Demolish' 3,023 all-time (1997-08-04 to
               present), 148 in the old 730-day window (95% excluded by the old cap).
               ('Interior/Exterior Demolition', 888, is a renovation and is not read.)
  durham       webgis2.durhamnc.gov PublicServices/Inspections MapServer/10 "Demolition Permits",
               2,923 rows (2007-10 to present), 325 in the old 730-day window (89% excluded). No
               address on the layer: PID is the parcel cache's key (5 of 5 sampled hit), so the
               situs and owner come from the join.
  cary         data.townofcary.org OpenDataSoft "permit-applications", 87,184 permits;
               'BLDG - DEMOLISH - SNGL FAM HOME (B645)' + 'BLDG NON RES DEMOLITION (B649)' 442
               all-time, 138 in the old 730-day window (69% excluded).

WHAT A ROW MEANS
    A property with a demolition permit applied for or issued, ever (see DATE COVERAGE), cancelled
    and withdrawn permits dropped. A demolition permit is the owner's (or a buyer's) application,
    not a city order, so it carries raw["demolition_permit"] and no condemned flag, as
    new_hanover_demolition_permits does. Owner and owner mailing are kept where the permit carries
    them (Mecklenburg, Greensboro, Cary: property-record fields).

DATE COVERAGE (fixed 2026-10-14, date-coverage audit): FORECLOSURE_DEMOLITION_DAYS used to default
to 730 and was applied as a hard WHERE-clause floor on every feed's issue date, discarding a
demolition record the moment it turned two years old -- for Greensboro that silently dropped 95%
of its full, genuinely date-agnostic history. A years-old demolition permit on a structure still
standing is one of the strongest "zombie property" signals this engine has, so the WHERE clause no
longer carries a date floor by default: every feed is read ALL-TIME (`since=None`), bounded instead
by `_MAX_RECORDS_PER_FEED` (an explicit volume safety cap, matching this codebase's convention for
an unbounded WHERE clause -- see e.g. greenville_hard_distress._MAX_RECORDS -- set well above every
feed's measured all-time count with headroom for growth, not a narrower re-introduction of the same
bug). FORECLOSURE_DEMOLITION_DAYS still exists for an operator who explicitly wants a narrower
window (a quick/cheap sample run); set it to opt back into date-filtering.

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
    # 2026-10-14: AccelaAllPermits/FeatureServer/0 (the service this Feed pointed at since
    # 2026-10-07) now 404s -- the county migrated to this BuildingPermits service with an
    # unrelated field schema. See the module docstring's dated note for the worktype/permitdesc
    # classification split (legacy "Demolish" tag through 2017-03, "Demolish/Move Off" phrasing
    # since) and for why there is no owner-mailing street field on the new schema.
    Feed("mecklenburg", "Mecklenburg", None,
         "https://meckgis.mecklenburgcountync.gov/server/rest/services/BuildingPermits/FeatureServer/0",
         "https://www.mecknc.gov/LUESA/CodeEnforcement",
         ("permitnum", "permitdesc", "worktype", "permitstat", "issuedate",
          "projadd", "parcelnum", "taxjuris", "zipcode",
          "ownname", "owncity", "ownstate", "ownzipcode"),
         {"permit": "permitnum", "status": "permitstat", "date": "issuedate",
          "address": "projadd", "parcel": "parcelnum", "zip": "zipcode",
          "city": "taxjuris", "owner": "ownname",
          "mail": ("owncity", "ownstate", "ownzipcode"),
          "mail_state": "ownstate",
          # worktype carries the legacy 'Demolish' tag (through 2017-03) but is blank on
          # every current-era row -- permitdesc's free text is the only description a
          # post-2017 row has (see arcgis_where's mecklenburg branch).
          "type": ("worktype", "permitdesc")}),
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
         ("PermitNum", "PID", "PIN15", "ISSUE_DATE", "CO_SIGNOFF_DATE", "PROJECT_TYPE", "TYPE",
          "PmtStatus"),
         # PID is Durham's 6-digit parcel id, which validation nulls as too short (206 rows on the
         # 2026-10-08 run); PIN15 on the same row is the 10-digit PIN, NC OneMap's `parno` for
         # Durham (PID is its `altparno`), so it is the parcel id and PID stays in the raw block.
         {"permit": "PermitNum", "status": "PmtStatus", "date": "ISSUE_DATE", "parcel": "PID",
          "parcel_long": "PIN15", "type": "TYPE"}),
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


def arcgis_where(feed: Feed, since: Optional[datetime]) -> str:
    """`since=None` (the default run) pulls the feed's full all-time history -- see the
    module docstring's DATE COVERAGE note. `since` set narrows to a sample window, same
    shape as before 2026-10-14."""
    if feed.name == "mecklenburg":
        # Two non-overlapping classifications of the same thing, see the module docstring:
        # the legacy exact tag (through 2017-03) and the phrase the county's system has used
        # for every demolition since (2017-04 to present).
        base = "(worktype='Demolish' OR permitdesc LIKE '%Demolish/Move Off%')"
        return base if since is None else f"{base} AND issuedate >= DATE '{since:%Y-%m-%d}'"
    if feed.name == "greensboro":
        base = "ApplicationType LIKE 'Total Demolish%'"
        return base if since is None else f"{base} AND IssuedDate >= DATE '{since:%Y-%m-%d}'"
    return "1=1" if since is None else f"ISSUE_DATE >= DATE '{since:%Y-%m-%d}'"


def cary_where(since: Optional[datetime]) -> str:
    types = ",".join(f'"{t}"' for t in CARY_TYPES)
    base = f"permittypedesc in ({types})"
    return base if since is None else f"{base} and applieddate >= date'{since:%Y-%m-%d}'"


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
    if isinstance(f, str):
        return clean(a.get(f))
    if isinstance(f, tuple):
        # a fallback CHAIN for one role (unlike "mail", which is a set of parts to join
        # elsewhere): first non-blank wins. Mecklenburg's post-migration "type" role needs
        # this -- `worktype` is blank on every current-era row, see the module docstring.
        for cand in f:
            v = clean(a.get(cand))
            if v:
                return v
    return None


#: validation._validate_parcel_id nulls a parcel id shorter than this.
_MIN_PID_LEN = 7


def parcel_of(a: dict, feed: Feed) -> Optional[str]:
    """The feed's parcel id, or its long form (`parcel_long`) when the short one would be nulled."""
    short = _get(a, feed, "parcel")
    long_ = _get(a, feed, "parcel_long")
    if long_ and len(long_) >= _MIN_PID_LEN and (not short or len(short) < _MIN_PID_LEN):
        return long_
    return short or long_


def group_permits(feed: Feed, rows: Iterable[dict]) -> list[dict]:
    """One group per property (parcel, else address) for one feed; dead permits dropped."""
    groups: dict[str, dict] = {}
    for a in rows:
        a = drop_sensitive(a)
        if _DEAD.search(_get(a, feed, "status") or ""):
            continue
        parcel, addr = parcel_of(a, feed), _get(a, feed, "address")
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
    parcel, addr = parcel_of(a, feed), _get(a, feed, "address")
    owner = _get(a, feed, "owner")
    latest = permits[0]["date"].date().isoformat() if permits and permits[0]["date"] else None
    raw: dict[str, Any] = {"demolition_permit": {
        "feed": feed.name, "count": len(permits), "latest_date": latest,
        "permits": [{**p, "date": p["date"].date().isoformat() if p["date"] else None} for p in permits[:10]],
        "source": SLUG,
    }}
    short = _get(a, feed, "parcel")
    if short and short != parcel:
        raw["demolition_permit"]["county_parcel_id"] = short
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


#: Volume safety cap per feed (not a date filter): well above every feed's measured
#: all-time count (mecklenburg 13,992, greensboro 3,023, durham 2,923, cary 442 as of
#: 2026-10-14) with room to grow, so a WHERE clause with no date floor still can't pull an
#: unbounded amount if a feed's volume changes unexpectedly. Matches this codebase's
#: existing convention for an all-time/dateless query (see e.g. greenville_hard_distress).
_MAX_RECORDS_PER_FEED = 50_000


class NCMetroDemolitionPermits(BaseScraper):
    slug = SLUG
    name = "NC metro demolition permits (Mecklenburg, Greensboro, Durham, Cary)"
    category = "city_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        #: unset (the default) -> no date floor at all, every feed's full all-time
        #: history; set -> the old narrower-sample behavior, for an explicit quick run.
        since: Optional[datetime] = None
        days_raw = os.environ.get(ENV_DAYS)
        if days_raw:
            try:
                days = int(days_raw)
                since = datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None
            except ValueError:
                since = None
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
    def _one(c, feed: Feed, since: Optional[datetime]):
        async def _run() -> list[dict]:
            if feed.name == "cary":
                return await _cary_rows(c, feed, since)
            return await fetch_attrs(c, feed.url, feed.fields, where=arcgis_where(feed, since),
                                     max_records=_MAX_RECORDS_PER_FEED)
        return _run
