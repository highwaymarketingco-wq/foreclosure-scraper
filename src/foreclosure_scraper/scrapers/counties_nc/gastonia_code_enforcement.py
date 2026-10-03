"""City of Gastonia NC — CityView code-enforcement case locator, bulk spatial query.

WHY THIS EXISTS
    `code_vacancy` (code-enforcement / vacant-structure) is genuinely covered in
    only 4 of 18 flip-footprint counties (`docs/HANDOFF.md` 2026-09-30 audit item
    73: Henderson, Buncombe, Lincoln NC + Spartanburg SC). Gaston already has
    `gastonia_vacant`/`gaston_vacant` scrapers, but those key off the county
    assessor's `VacantImpro` flag — vacant LAND, not a code-enforcement CASE on a
    structure — so they do not count toward this family (confirmed correctly
    excluded, see the same audit). This module is the real thing: an actual
    code-enforcement case record (nuisance, junk vehicles, minimum housing,
    commercial maintenance, unauthorized encampment, etc.) with a case number,
    status, address, and the county parcel id.

    Multiple prior discovery rounds (`docs/round2_executive.md`,
    `docs/round3_executive.md`, `docs/road_to_100_build_queue.md` #6) flagged
    the City of Gastonia's CityView portal as a real, live, anonymous, buildable
    source and left it unbuilt (`docs/build_queue_2026-09-20.md`: "OPEN. ...no
    CodeEnforcement/Locator reference"). One recorded domain,
    `devsvcs.cityofgastonia.com`, is dead (DNS NXDOMAIN, confirmed live
    2026-09-30) — that is what an earlier round's "endpoint 302s to NotFound.
    Dead" note (`docs/source_backlog_closure.md`) was hitting. The LIVE domain,
    confirmed working 2026-09-30, is `devsvcs.gastonianc.gov`.

THE SITE (verified live 2026-09-30)
    `GET /CodeEnforcement/Locator?category=CE` — the public "Complaint Search"
    page. No login, no CAPTCHA. It sets a plain ASP.NET session cookie plus an
    anti-forgery token (a session handshake, not an authentication wall — the
    page is anonymous and the same cookie is handed to every visitor).

    The page's own map config exposes a spatial bulk-query AJAX endpoint used
    by its "search this map area" feature:

        POST /CodeEnforcement/LocatorResultsPolygon
        body: Category=CE, WKID=3857, Points[i][X]/[Y]=<ring>, plus five
              unrelated module flags the page always sends (all "false")

    POSTing a rectangle covering the WHOLE city (the exact extent the page's
    own `mapConfig` carries: XMin=-9066197.26 XMax=-9011029.73 YMin=4184187.95
    YMax=4209418.66, WKID 3857) returns a `LocationMarkers` JSON array with, for
    every case in that area: `ReferenceNumber` (case #), `ApplicationTypeDescription`
    (violation type), `Status`, `PrimaryLocation` (full postal address),
    `MapPoint` (X/Y in 3857), and `MapRelationValue` (`LayerName="Parcels"`,
    `AttributeName="AKPAR"`, `AttributeValue=<id>`) — the county parcel join key.
    No login, no token check on this endpoint beyond the session cookie.

    **Hard cap, confirmed live**: `LocationMarkers` never exceeds 1000 rows per
    call, even though the true count is higher — querying the west HALF and the
    east HALF of the same city extent separately each independently returned
    1000 rows too (i.e. 2000+ across the two halves, not the 1000 the whole-city
    query implied). Per this repo's own standing rule ("a round number like 1000
    is a cap until proven otherwise", `CLAUDE.md`), the whole-city single call is
    NEVER trusted; `_query_bbox` recurses into quadrants whenever a call returns
    exactly `PAGE_CAP` rows, until each leaf is under the cap or a minimum cell
    size is hit.

    The CityView `AKPAR` id is the county assessor's **PID, not the PIN**
    (verified live 2026-09-30: querying Gaston County's own parcel layer,
    `.../PublicGIS/Parcels/FeatureServer/11`, for `AKPAR='110880'` returns
    `PIN='3555-31-0320'`, `PID='110880'`, `AKPAR='110880'` — AKPAR and PID are
    identical, PIN is a different format entirely, and `PHYSSTRADD` on that row
    exactly matches the CityView case's `PrimaryLocation`). Every other Gaston
    source in this repo (`gaston_vacant.py`, `enrichment_arcgis.NC_GIS["Gaston"]`)
    keys `parcel_id` off `PIN`, so writing the raw `AKPAR` value as `parcel_id`
    here would silently miss the dedupe join it is supposed to make. This module
    batch-resolves every case's `AKPAR` against that same county layer (one
    `AKPAR IN (...)` query per ~200 ids) to recover the real `PIN` + owner name
    (`CURR_NAME1`) before building listings — this is the "it carries the county
    PIN so it skips the resolver" property `docs/round2_executive.md` describes.

    The locator API has no date field and no server-side open/closed filter.
    Status is free text (`Closed`, `Closed - No Violations`, `Closed - Duplicate
    Case Entry`, `Closed - Remedied`, `Closed - Dismissed`, `Open`, `Notice/Order
    Sent`, `Abatement`, `Referred`, `Citation Issued`, `Order to Repair[/Vacate]`
    — live sample, 2026-09-30). Matching Henderson's established rule in this
    repo (`henderson_code_violations.py`): treat CLOSED as a NEGATIVE match
    (anything starting "Closed") so a status the city adds later defaults to
    OPEN (a lead), not to silently invisible. A parcel is only emitted while at
    least one of its cases is open.

    A case number carries its filing year (`CEPNU20262400` -> type `PNU`, year
    `2026`, sequence `2400`) — used only as `latest_case_year` context; there is
    no per-case filed/received date in this API, unlike Henderson's ArcGIS layer.

2026-10-03 validation (live full-city crawl, 19,429 unique cases / 3,304 open /
1,493 properties with >=1 open case): this module had the identical bug SHAPE
Henderson's code-enforcement scraper had before its 2026-10-02 fix (commit
19d3888e) — every open case granted full PROPERTY `code_enforcement` credit
regardless of `ApplicationTypeDescription`, because `vacancy_adjacent` was never
wired. Gastonia's own category taxonomy is NOT the same vocabulary as
Henderson's ArcGIS `violationType` domain (confirmed live; this is a different
CityView `ApplicationTypeDescription` field, free text, no coded domain), so the
category list had to be independently live-verified rather than reused.

Live category breakdown of the 3,304 OPEN cases that day, with each real case's
free-text `Description` field pulled from the `StatusReference` detail page to
disambiguate "paperwork" from "physical condition" wherever the bare category
label alone was ambiguous:
  - Vegetation/Weeds (1,533, the single largest category) — already excluded
    before this validation (see `_SEVERE` below); confirmed correctly excluded,
    same reasoning as Henderson's Zoning: too common and too low-specificity
    (both occupied and vacant properties get weed complaints) to be real
    evidence on its own.
  - Public Nuisance (857), Housing (262), Unauthorized Encampment (41), Junk
    Vehicles (21), Commercial Maintenance Code (7) — already on `_SEVERE`;
    sampled detail pages confirm genuine physical-condition/blight language
    (one Commercial Maintenance Code case: "Old funeral home. Carport falling
    down... paint peeling... homeless people sleeping between hotel and garage
    building" — textbook vacant/blighted structure).
  - Abandoned Vehicle (11 open) — NOT previously on `_SEVERE`; all 3 sampled
    cases describe genuine junk/debris ("Junk trash debris in yard", "Abandoned
    Vehicles, tow truck... never move", "Abandoned 18 wheelers, cabs, cars, RV.
    Bunch of junk") — the same concept as Junk Vehicles, just a different label.
    Added to `_SEVERE`.
  - Zoning/Land Use (299), Street/Sidewalk Obstruction (79), Building Code (63),
    Fence/Wall (43), Signage (39), Tree Removal (23), Livestock (8), Historic
    District (8), Graffiti (7), Drought Violation (3) — sampled detail pages
    confirm these are paperwork/permit/right-of-way/animal-nuisance categories,
    NOT property condition: Building Code samples were a lapsed fire-alarm
    monitoring contract, a vague "code violations" report, and an unlicensed-
    contractor complaint; Historic District samples were a resident installing
    a pool and running underground utility lines (actively improving the
    property, the opposite of vacant); Fence/Wall samples were height/placement
    disputes; Street/Sidewalk Obstruction samples were a trash can, a
    basketball goal, and a dirt pile in the road, none about the subject
    structure. Graffiti (7 open) was deliberately left OFF `_SEVERE` despite one
    sample describing graffiti "on this vacant residence" — 2 of the 3 sampled
    cases were graffiti on a stop sign and a utility line, unrelated to the
    subject parcel's own condition, too noisy a category on this small a sample
    to trust.

Net: of the 1,493 properties with at least one open case that day, 719 (48.2%)
carry ONLY non-vacancy-adjacent open cases — essentially the same scale of
over-crediting Henderson had (53.1%). Fixed the same way: `vacancy_adjacent` is
now wired from `severe` (which `signal_freshness.code_enforcement_open()`
already knows how to read, per the Henderson/Lincoln precedent) so a
Vegetation/Weeds- or Zoning/Land-Use-only property still ships on the board
truthfully (`has_open` stays true) but withholds PROPERTY credit.

Free, public, anonymous. No CAPTCHA, no login, no WAF. Gate with
FORECLOSURE_GASTONIA_CODE=0.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime
from typing import Any, Iterable

import httpx
import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_GASTONIA_CODE"

BASE = "https://devsvcs.gastonianc.gov"
LOCATOR_URL = f"{BASE}/CodeEnforcement/Locator?category=CE"
POLYGON_URL = f"{BASE}/CodeEnforcement/LocatorResultsPolygon"
DASHBOARD_URL = LOCATOR_URL

#: City-limits search extent, WKID 3857 — taken verbatim from the portal's own
#: `mapConfig.XMin/XMax/YMin/YMax` (the city's own definition of its search area,
#: not a guessed bounding box). Verified live 2026-09-30.
CITY_XMIN, CITY_XMAX = -9066197.262812756, -9011029.72586616
CITY_YMIN, CITY_YMAX = 4184187.9468681049, 4209418.6639962066

#: Observed hard cap on `LocationMarkers` per polygon query (verified live
#: 2026-09-30: the whole-city extent AND each independent half all returned
#: exactly this many). Any leaf hitting this is truncated, not complete.
PAGE_CAP = 1000

#: Stop subdividing below this cell size (map units, ~feet in 3857 at this
#: latitude) even if still at the cap, so one hot spot cannot spin the crawl
#: into an unbounded number of requests.
_MIN_CELL = 200.0
_MAX_DEPTH = 7

#: Gaston County's own parcel layer -- resolves CityView's `AKPAR` (confirmed
#: live to be the PID, not the PIN) to the real PIN + owner every other Gaston
#: source in this repo keys off.
PARCEL_LAYER = ("https://gis.gastoncountync.gov/publicgis/rest/services/"
                "PublicGIS/Parcels/FeatureServer/11")

_CLOSED_RE = re.compile(r"^\s*closed", re.I)

#: ApplicationTypeDescription values that imply physical deterioration/dumping
#: rather than paperwork (confirmed live 2026-10-03 against this feed's own
#: category vocabulary and real case Descriptions -- NOT the same vocabulary as
#: Henderson's ArcGIS violationType domain, so reused only in spirit, not
#: literally). Zoning/Land Use, Street/Sidewalk Obstruction, Building Code,
#: Fence/Wall, Signage, Tree Removal, Livestock, Historic District, Graffiti,
#: Drought Violation, and (deliberately, see module docstring) Vegetation/Weeds
#: do NOT match -- everything open still ships on the board; this gates the
#: `distressed` flag AND the `code_enforcement`/`vacancy_adjacent` PROPERTY-
#: scoring signal, not just a label (same convention as
#: henderson_code_violations._SEVERE).
_SEVERE_RE = re.compile(
    r"(housing|nuisance|junk|encampment|commercial maintenance|abandoned vehicle)",
    re.I)
_CASE_YEAR_RE = re.compile(r"^CE[A-Z]+(\d{4})\d+$")

_POLY_FLAGS = {
    "AppealPeriodStatusesOnly": "false",
    "IsExciseTaxSearch": "false",
    "IsRenewalsSearch": "false",
    "IsSubmittalsSearch": "false",
    "IsPumpingInformationSearch": "false",
    "IsAppealPeriodCommentsSearch": "false",
    "NewIntermentSearch": "false",
}


def _is_closed(status: Any) -> bool:
    return bool(_CLOSED_RE.match(str(status or "")))


def _case_year(ref: Any) -> int | None:
    m = _CASE_YEAR_RE.match(str(ref or "").strip())
    return int(m.group(1)) if m else None


def _web_mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """WKID 3857 -> WGS84 lon/lat."""
    lon = x / 20037508.34 * 180.0
    lat_rad = y / 20037508.34 * 180.0
    lat = 180.0 / math.pi * (2 * math.atan(math.exp(lat_rad * math.pi / 180.0)) - math.pi / 2)
    return lon, lat


def _bbox_body(xmin: float, xmax: float, ymin: float, ymax: float) -> dict[str, str]:
    ring = [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    data: dict[str, str] = {"Category": "CE", "WKID": "3857", **_POLY_FLAGS}
    for i, (x, y) in enumerate(ring):
        data[f"Points[{i}][X]"] = str(x)
        data[f"Points[{i}][Y]"] = str(y)
    return data


def parse_polygon_response(payload: dict) -> list[dict]:
    """Pull the marker list out of a `LocatorResultsPolygon` JSON body."""
    return payload.get("LocationMarkers") or []


async def _query_bbox(http: httpx.AsyncClient, xmin: float, xmax: float,
                       ymin: float, ymax: float, depth: int = 0,
                       on_leaf=None) -> list[dict]:
    """Recurse into quadrants wherever a cell hits PAGE_CAP.

    When `on_leaf` is given, it is awaited with each TRUE leaf's markers (a
    cell that did NOT need further splitting) as soon as that cell resolves,
    instead of waiting for the whole city to finish -- this is what lets
    `fetch()` populate `self.partial` incrementally, so a scraper.timeout
    mid-crawl still ships every property already resolved rather than nothing
    (a full crawl here is ~60-100 requests; see GastoniaCodeEnforcement.timeout_s).
    A capped PARENT cell's markers are never handed to `on_leaf` (its children
    re-fetch the same properties), which also avoids double-processing.
    """
    resp = await http.post(POLYGON_URL, data=_bbox_body(xmin, xmax, ymin, ymax),
                            headers={"X-Requested-With": "XMLHttpRequest",
                                     "Referer": LOCATOR_URL})
    resp.raise_for_status()
    markers = parse_polygon_response(resp.json())
    log.info("gastonia_code.leaf", depth=depth, count=len(markers),
             width=round(xmax - xmin), height=round(ymax - ymin))
    is_leaf = len(markers) < PAGE_CAP or depth >= _MAX_DEPTH or (
        (xmax - xmin) < _MIN_CELL or (ymax - ymin) < _MIN_CELL)
    if is_leaf:
        if len(markers) >= PAGE_CAP:
            log.warning("gastonia_code.cell_floor_hit", depth=depth,
                        xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
        if on_leaf is not None:
            await on_leaf(markers)
        return markers
    xmid, ymid = (xmin + xmax) / 2, (ymin + ymax) / 2
    out: list[dict] = []
    for qx0, qx1, qy0, qy1 in (
        (xmin, xmid, ymin, ymid), (xmin, xmid, ymid, ymax),
        (xmid, xmax, ymin, ymid), (xmid, xmax, ymid, ymax),
    ):
        out.extend(await _query_bbox(http, qx0, qx1, qy0, qy1, depth + 1, on_leaf))
    return out


def _group_key(m: dict) -> tuple[str, str] | None:
    """One listing per PROPERTY: the county parcel id when present, else address."""
    mrv = m.get("MapRelationValue") or {}
    if mrv.get("LayerName") == "Parcels" and mrv.get("AttributeValue"):
        return ("pid", str(mrv["AttributeValue"]).strip())
    addr = m.get("PrimaryLocation")
    if addr:
        return ("addr", str(addr).strip().upper())
    return None


async def resolve_parcels(http: httpx.AsyncClient, pids: list[str]) -> dict[str, dict]:
    """AKPAR/PID -> {pin, owner} via Gaston County's own parcel layer.

    Best-effort: a failed batch costs the PIN join for those parcels (they
    still ship with parcel_id=None + address + lat/lng), not the leads.
    """
    idx: dict[str, dict] = {}
    uniq = sorted({p for p in pids if p})
    for i in range(0, len(uniq), 200):
        chunk = uniq[i:i + 200]
        quoted = ",".join("'" + p.replace("'", "''") + "'" for p in chunk)
        try:
            rows = await agw.query_attributes(
                http, PARCEL_LAYER, where=f"AKPAR IN ({quoted})",
                out_fields="AKPAR,PIN,CURR_NAME1", page=200, max_records=5000)
        except Exception as exc:  # noqa: BLE001
            log.warning("gastonia_code.parcel_join_fail", error=str(exc)[:200],
                        chunk_size=len(chunk))
            continue
        for a in rows:
            pid = str(a.get("AKPAR") or "").strip()
            if not pid:
                continue
            pin = str(a.get("PIN") or "").strip() or None
            owner = str(a.get("CURR_NAME1") or "").strip() or None
            idx[pid] = {"pin": pin, "owner": owner}
    return idx


def build_listing(markers: list[dict], parcels: dict[str, dict] | None = None,
                  now: datetime | None = None) -> Listing | None:
    """Fold every case at one property into a single Listing. None if every
    case there is closed (not a live lead)."""
    now = now or datetime.utcnow()
    parcels = parcels or {}
    if not markers:
        return None

    mrv = (markers[0].get("MapRelationValue") or {})
    pid = (str(mrv["AttributeValue"]).strip()
           if mrv.get("LayerName") == "Parcels" and mrv.get("AttributeValue") else None)
    pinfo = parcels.get(pid, {}) if pid else {}
    pin = pinfo.get("pin")
    owner = pinfo.get("owner")

    address = next((str(m["PrimaryLocation"]).strip() for m in markers
                    if m.get("PrimaryLocation")), None)
    if not pin and not address:
        return None

    lat = lng = None
    for m in markers:
        mp = m.get("MapPoint") or {}
        if mp.get("X") is not None and mp.get("Y") is not None:
            try:
                lng, lat = _web_mercator_to_lonlat(float(mp["X"]), float(mp["Y"]))
            except (TypeError, ValueError):
                lat = lng = None
            break

    cases: list[dict] = []
    types: set[str] = set()
    years: list[int] = []
    open_count = 0
    severe = False
    for m in markers:
        ref = m.get("ReferenceNumber")
        status = str(m.get("Status") or "unknown")
        ctype = str(m.get("ApplicationTypeDescription") or "unknown")
        is_open = not _is_closed(status)
        if is_open:
            open_count += 1
            if _SEVERE_RE.search(ctype):
                severe = True
        types.add(ctype)
        yr = _case_year(ref)
        if yr:
            years.append(yr)
        cases.append({"case_id": ref, "violation": ctype, "status": status,
                      "open": is_open})

    if open_count == 0:
        return None

    raw: dict[str, Any] = {
        # Same shape enrichment_code_enforcement/henderson_code_violations write,
        # so distress_score.code_enforcement_open() and every downstream reader
        # works as-is without a new family branch.
        "code_enforcement": {
            "county": "Gaston",
            "city": "Gastonia",
            "open_violations": open_count,
            "total_violations": len(cases),
            "prior_cases": max(len(cases) - open_count, 0),
            "repeat_offender": len(cases) >= 3,
            "violation_types": sorted(types),
            "severe": severe,
            "violations": cases[:8],
            "has_open": True,
            # 2026-10-03: has_open stays literally true (there IS an open case) --
            # vacancy_adjacent is the separate, explicit answer to "does any open
            # case's CATEGORY actually indicate vacancy/condemnation/structural
            # distress", which signal_freshness.code_enforcement_open() now gates
            # PROPERTY credit on (same convention as henderson_code_violations.py's
            # 2026-10-02 fix, commit 19d3888e). A Zoning/Land-Use- or Vegetation/
            # Weeds-only property still ships with its real case data.
            "vacancy_adjacent": severe,
            "latest_case_year": max(years) if years else None,
            "source": "gastonia_cityview_locator",
        },
    }
    if severe:
        raw["distressed"] = True

    headline = sorted(types)[0] if types else "code violation"
    desc = (f"Open code-enforcement case ({headline}) — City of Gastonia, NC"
            + (f"; owner {owner}" if owner else "")
            + (f"; {len(cases)} total case(s) at this property" if len(cases) > 1 else ""))

    open_cases = [c for c in cases if c["open"]]
    head_case = open_cases[0] if open_cases else cases[0]

    return Listing(
        source=GastoniaCodeEnforcement.slug,
        source_url=DASHBOARD_URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Gaston",
        city="Gastonia",
        street_address=address,
        parcel_id=pin,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        latitude=lat,
        longitude=lng,
        case_number=head_case.get("case_id"),
        description=desc,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class GastoniaCodeEnforcement(BaseScraper):
    slug = "counties_nc.gastonia_code_enforcement"
    name = "City of Gastonia NC Code Enforcement (CityView locator, spatial bulk query)"
    category = "motivated_seller"
    expected_min_count = 25
    # Live-verified 2026-09-30: a full recursive crawl of the whole city took
    # 69 polygon requests / 446s (~6.5s each: large payload + this repo's
    # deliberate per-host throttle) and landed 19,406 unique historical cases,
    # 1,487 properties with at least one still open, 1,470 PIN-joined (98.9%).
    # timeout_s left generous above the measured run; BaseScraper.safe_run()
    # ships whatever is in self.partial if a future run (more total cases,
    # slower network) still isn't enough.
    timeout_s = 900.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("gastonia_code.disabled")
            return []
        now = datetime.utcnow()
        seen_refs: set[str] = set()
        total_markers = 0

        async with client(timeout=30.0) as http:
            # Session handshake (cookie only) -- anonymous, not a login/CAPTCHA wall.
            await http.get(LOCATOR_URL)

            async def _on_leaf(markers: list[dict]) -> None:
                # Process THIS leaf's properties immediately and append to
                # self.partial as we go -- a property is a point, so it is
                # entirely contained in exactly one leaf cell; no cross-leaf
                # grouping is needed. This is what lets a mid-crawl timeout
                # ship every property resolved so far instead of nothing.
                nonlocal total_markers
                total_markers += len(markers)
                fresh = []
                for m in markers:
                    ref = m.get("ReferenceNumber")
                    if ref and ref not in seen_refs:
                        seen_refs.add(ref)
                        fresh.append(m)
                groups: dict[tuple[str, str], list[dict]] = {}
                for m in fresh:
                    key = _group_key(m)
                    if key:
                        groups.setdefault(key, []).append(m)
                pids = [k[1] for k in groups if k[0] == "pid"]
                parcels = await resolve_parcels(http, pids)
                for feat_group in groups.values():
                    li = build_listing(feat_group, parcels, now=now)
                    if li:
                        self.partial.append(li)

            await _query_bbox(http, CITY_XMIN, CITY_XMAX, CITY_YMIN, CITY_YMAX,
                              on_leaf=_on_leaf)

        out = list(self.partial)
        log.info("gastonia_code.parsed", raw_cases=total_markers,
                 unique_cases=len(seen_refs), listings=len(out),
                 pin_joined=sum(1 for li in out if li.parcel_id))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = GastoniaCodeEnforcement()
        rows = await s.safe_run()
        joined = sum(1 for li in rows if li.parcel_id)
        severe = sum(1 for li in rows if (li.raw or {}).get("distressed"))
        print(f"outcome={s.last_outcome} count={len(rows)} pin_joined={joined} "
              f"severe={severe}")
        for li in rows[:15]:
            ce = li.raw["code_enforcement"]
            print(f"  {(li.owner_name or '')[:24]:24} pin={li.parcel_id or '-':14} "
                  f"open={ce['open_violations']} total={ce['total_violations']} "
                  f"{','.join(ce['violation_types'])[:30]:30} "
                  f"{(li.street_address or '')[:32]}")

    asyncio.run(_main())
