"""Code enforcement violation enrichment.

Cities publish open code violations (condemned, unsafe structure, junk
vehicles, overgrowth, missing permits) via their open-data portals. Direct
distress signal — properties with active violations are 60-70% likely to
hit foreclosure or tax sale within 18 months.

Coverage: NONE currently active. The previously-wired "Charlotte" ArcGIS
endpoint (services5.arcgis.com/86gdKBxZf7GIt2Or/.../Code_Enforcement_Cases)
was wrong — it actually serves City of Yucaipa, CA code-enforcement cases,
which are 2,000+ miles out of footprint. It has been removed rather than
substituted: no free, public code-enforcement feed for an in-footprint NC/SC
city has been confirmed yet. The query/match/scoring machinery below stays
intact so a verified in-footprint endpoint can be slotted into
``CITY_ENDPOINTS`` later. With the dict empty, ``enrich_with_code_enforcement``
is a graceful no-op.

REMOVED 2026-10-03 — "Asheville" (`gis.ashevillenc.gov/.../AccelaServicesView/
MapServer/0`), wired 2026-07-01 (commit `311ba4fc`) on the strength of an
HTTP 200 + real addressed cases. That check never looked at the DATES. Live
re-verification today, tasked with building a standalone scraper off this
same endpoint, found the entire 2,738-row table is a FROZEN snapshot: every
date field on every row (`date_opened`, `date_statused`, `date_closed`,
`record_status_date`, `date_assigned`) maxes out at 2018-12-14, confirmed via
direct `outStatistics` MIN/MAX queries against the live service, both overall
and per `record_type_category` (Housing Code Referral, Damage-Incident, Junked
Vehicles, FMO Referral, Stop Work Order, Other Referral, Short Term Rental,
Land Use, Sign Violation — every one of them, no exceptions). Sample records
pulled across those same categories (verbatim `description` text) are all
dated 2016 with `record_status` already "Closed". Status values that read as
open today (`Open` 68, `NOV Mailed` 41, `NOV Served` 50, `Citation Pending`
32, `Unsafe Structure` 5, `Deteriorated Structure` 13, etc.) all have their
OWN `record_status_date` frozen at the same Dec-2018 ceiling — there is no
way to tell whether any of them are still open today; the far likelier
explanation, consistent with `city_websites/asheville_min_housing.py`'s
independent 2026-09-15 finding that Asheville's current minimum-housing
process publishes no case registry at all, is that this ArcGIS view's sync
from Accela simply stopped running after Dec 2018 and nobody pointed it at a
successor system. This enricher was matching every CURRENT Asheville-city
lead's address against these 8-10-year-old frozen records and granting
`has_open: True` / `code_enforcement` PROPERTY credit whenever a stale
"Open"/"NOV Mailed"/etc. status happened to match — a false-positive
distress signal manufactured from dead data, the same failure shape
`city_websites/charlotte_open_data.py`'s own docstring already names and
rejects for a different stale Mecklenburg permits layer ("stale, not a
current feed. Dropped rather than land dead data."). Removed rather than
"fixed" — there is no live successor endpoint to substitute (see
`src/foreclosure_scraper/scrapers/counties_nc/asheville_code_enforcement.py`'s
own docstring for the full standalone-scraper investigation that found this).

Free, ArcGIS REST endpoints, no auth.

LIFECYCLE (audit 2026-09-21, F12). The block is written even when every violation is closed
(`has_open` False), and used to be left in place forever once the feed stopped returning the
case, so a resolved case scored as an open one. Now: the scorer counts the block only while
`has_open` is true (`signal_freshness.code_enforcement_open`); each write is stamped
(`stamped_at`, `stale_after`, `source`); and a lookup that ANSWERED with no matching case
clears a block this enricher wrote earlier. A lookup that errored clears nothing.
"""
from __future__ import annotations

import asyncio
import math
import re
from typing import Any, Optional

import structlog

from .http_client import client
from .models import Listing
from .signal_freshness import stamp

log = structlog.get_logger()

#: Marker on blocks this enricher wrote, so it only ever clears its own.
_SOURCE_TAG = "city_open_data"
#: A stamped block stops meaning anything this long after it was written unless a later run
#: re-confirms it.
_TTL_DAYS = 120


# City open-data endpoints — public ArcGIS FeatureServer queries.
# Discovered via each city's open-data portal (data.<city>.gov / ArcGIS Hub).
#
# HISTORY, kept because the caution is the right one: a former "Charlotte" entry
# pointed at services5.arcgis.com/86gdKBxZf7GIt2Or/.../Code_Enforcement_Cases, which
# is actually the City of YUCAIPA, CALIFORNIA -- out of footprint by ~2,000 miles.
# Disabling it was correct. Many city-of-* portals rotate FeatureServer URLs, so
# confirm the host and owning org actually serve the intended city before wiring one.
#
# 2026-09-10: Charlotte is BACK, on the city's OWN host (gis.charlottenc.gov, the HNS
# = Housing & Neighborhood Services service), verified live. The old note said "no
# in-footprint NC/SC city code-enforcement feed has been verified yet" -- that had
# stopped being true and the sweep found it. code_vacancy was present in only 2 of 18
# footprint counties on the live board, the worst-covered lane in the engine.
#
#   CodeEnforcementNewAndOpenCases   3,966 features, verified 2026-09-10
#   CodeEnforcementOrderstoDemolish     17 features -- a STANDING ORDER TO DEMOLISH is
#                                       the strongest single distress signal in this
#                                       lane, so it is carried as its own entry
#
# Asheville AccelaServicesView (2,738 features) was here 2026-07-01 through
# 2026-10-03 -- REMOVED, see the module docstring's 2026-10-03 note. Every row's
# every date field is frozen at 2018-12-14; it was manufacturing false "open
# violation" matches against today's real Asheville leads from an 8-10-year-dead
# snapshot. Do not re-add without live-reverifying the date fields first.
#
# Charlotte rows carry ParcelId, which is a direct Mecklenburg parcel join key -- much
# stronger than the 250ft lat/lng proximity test this enricher falls back on. The two
# Charlotte layers OVERLAP (the same case number appears in both), so a property under
# a demolition order will tag twice; that is intended, and the demolish tag is the one
# that matters.
CITY_ENDPOINTS: dict[str, dict] = {
    # City of Charlotte, Housing & Neighborhood Services. Mecklenburg is outside the
    # 18-county FORECLOSURE footprint but inside the statewide DISTRESSED scope.
    "Charlotte": {
        "url": "https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementNewAndOpenCases/MapServer/0",
        "addr_fields": ("FullAddress",),
        "violation_fields": ("CaseType", "DetailedDescription"),
        "status_fields": ("CaseStatus",),
        "date_fields": ("DateCreated",),
        "parcel_field": "ParcelId",
    },
}

# Wake County Code Enforcement (hosted on the Raleigh open-data portal, data.raleighnc.gov,
# but live-verified 2026-10-28 to cover the whole county: 489 live cases spanning Raleigh,
# Cary, Apex, Garner, Wake Forest, Fuquay Varina, Zebulon, Wendell, Knightdale, Rolesville,
# Youngsville, New Hill, Willow Spring -- not Raleigh-city-only. maxDate across all rows was
# 2026-10-27 (one day before this check), a genuinely live rolling feed, NOT the frozen-sync
# trap this module's own docstring warns about for Asheville/the old Charlotte guess --
# checked the actual date range before trusting it, not just a 200. No parcel/owner field,
# address-match only (same addr_fields mechanism Charlotte already uses). CASE_STATUS uses
# compound text ("Closed - VIO Resolved", "Void", etc.) -- this is why
# _is_closed_status() replaced the old exact-match check for ALL cities, not just this one.
_WAKE_CFG = {
    "url": "https://services1.arcgis.com/a7CWfuGP5ZnLYE7I/arcgis/rest/services/codecases_90days_test/FeatureServer/0",
    "addr_fields": ("STREET_ADDRESS",),
    "violation_fields": ("CASE_TYPE", "DESCRIPTION"),
    "status_fields": ("CASE_STATUS",),
    "date_fields": ("OPENED_DATE",),
}
for _wake_city in ("Raleigh", "Cary", "Apex", "Garner", "Wake Forest", "Fuquay Varina",
                   "Zebulon", "Wendell", "Knightdale", "Rolesville", "Youngsville",
                   "New Hill", "Willow Spring"):
    CITY_ENDPOINTS[_wake_city] = _WAKE_CFG

#: Layers that are not "a violation" but a TERMINAL condition. A standing order to
#: demolish means the structure is coming down: the owner is about to lose the
#: improvement and keep the lot, which is the clearest motivated-seller state there is.
#: Kept separate from CITY_ENDPOINTS so it can carry its own severity rather than being
#: averaged into an ordinary Housing case.
SEVERE_ENDPOINTS: dict[str, dict] = {
    "Charlotte": {
        "url": "https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementOrderstoDemolish/MapServer/0",
        "addr_fields": ("FullAddress",),
        "violation_fields": ("CaseType", "DetailedDescription"),
        "status_fields": ("CaseStatus",),
        "date_fields": ("DateCreated",),
        "parcel_field": "ParcelId",
        "severity": "order_to_demolish",
    },
}


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def _street_keywords(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"^\d+\s*", "", s)
    s = re.sub(
        r"\b(N|S|E|W|NE|NW|SE|SW|North|South|East|West|"
        r"St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Ln|Lane|"
        r"Ct|Court|Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Trl|Trail|"
        r"Pkwy|Parkway|Cir|Circle)\b\.?",
        "", s, flags=re.I,
    )
    tokens = [t.strip(".,#") for t in s.split() if len(t) > 2]
    return max(tokens, key=len, default=s.strip())


#: A city's own compound status text (e.g. Wake County's "Closed - VIO Resolved",
#: "Closed – Inconclusive ", "Void") is still closed-equivalent even though it is not
#: byte-identical to the bare "closed"/"resolved" this module originally checked for -- an
#: exact-match test silently treated every one of those as OPEN. Prefix match on the same
#: convention this project already uses for this exact problem
#: (scrapers/counties_nc/gastonia_code_enforcement.py's own _is_closed/_CLOSED_RE).
_CLOSED_STATUS_PREFIXES = ("closed", "resolved", "void")


def _is_closed_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s.startswith(_CLOSED_STATUS_PREFIXES)


def _pick(attrs: dict, fields: tuple) -> Optional[str]:
    norm = {k.lower(): v for k, v in attrs.items()}
    for f in fields:
        v = norm.get(f.lower())
        if v not in (None, "", 0, "0"):
            return str(v)
    return None


async def _fetch_violations_for_listing(
    c, li: Listing, cfg: dict
) -> list[dict] | None:
    """Query the city ArcGIS for violations matching this listing's address.

    Returns the matching features; `[]` when the service ANSWERED and had none; `None` when
    it could not be asked (no address, or every attempt errored), so a caller never mistakes
    an outage for "the case is gone"."""
    if not li.street_address:
        return None
    keyword = _street_keywords(li.street_address)
    if not keyword:
        return None

    answered = False
    # Try each address-field name
    for addr_field in cfg["addr_fields"]:
        try:
            params = {
                "where": f"UPPER({addr_field}) LIKE '%{keyword.upper()}%'",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": "10",
                "f": "json",
            }
            # cfg["url"] is the LAYER url (test_every_endpoint_is_a_layer_url_not_a_query_url
            # enforces this); /query is the actual ArcGIS REST query sub-resource -- without it
            # this hits the layer's own metadata/schema endpoint (always 200, never has a
            # "features" key) and every single city has been silently getting 0 results
            # forever, confirmed live 2026-10-28 against Charlotte's own already-wired endpoint,
            # not just the new ones added this session.
            r = await c.get(cfg["url"].rstrip("/") + "/query", params=params, timeout=15.0)
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            answered = True
            feats = data.get("features", [])
            if feats:
                return feats
        except Exception:
            continue
    return [] if answered else None


def _proximity_filter(li: Listing, feats: list[dict]) -> list[dict]:
    """Narrow raw address-keyword hits to ones within ~250ft of the listing's own
    coordinates; returns `feats` unfiltered when the listing has no coordinates to
    check against (same fallback the main CITY_ENDPOINTS loop already uses)."""
    if not (li.latitude and li.longitude):
        return feats
    out = []
    for f in feats:
        geom = f.get("geometry") or {}
        glat, glon = geom.get("y"), geom.get("x")
        if glat is None or glon is None:
            continue
        if _haversine_miles(float(li.latitude), float(li.longitude),
                             float(glat), float(glon)) <= 0.05:
            out.append(f)
    return out


def _clear_stale_block(li: Listing, counts: dict) -> None:
    """The city answered and has no case at this address.

    Writes a dated negative wrapper (not just an empty pop) so this row satisfies
    gap_matrix.py's own "row"-scope contract -- "checked when the row carries the value
    OR a negative-result wrapper" -- which this enricher previously could never do: its
    only write path was the positive-match block below, so a true "ran, found nothing"
    answer was invisible to the gap list forever (audit 2026-10-16). Leaves a block a
    DIFFERENT producer wrote (county scraper or another enricher) untouched -- this
    enricher only ever overwrites its own prior write, by `source` tag."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    ce = li.raw.get("code_enforcement")
    if isinstance(ce, dict) and ce.get("source") != _SOURCE_TAG:
        return
    li.raw["code_enforcement"] = stamp(
        {"city": li.city, "has_open": False, "open_violations": 0, "total_violations": 0,
         "violations": [], "source": _SOURCE_TAG}, ttl_days=_TTL_DAYS)
    counts["cleared"] = counts.get("cleared", 0) + 1


async def enrich_with_code_enforcement(listings: list[Listing]) -> None:
    """For each listing in a covered city, look up open code-enforcement
    violations. Tag matched listings with the count + worst-severity violation.
    """
    if not listings:
        return

    # City detection by city name (case-insensitive)
    targets_by_city: dict[str, list[Listing]] = {}
    severe_targets_by_city: dict[str, list[Listing]] = {}
    for li in listings:
        if not li.city:
            continue
        city_norm = li.city.strip().title()
        if city_norm in CITY_ENDPOINTS:
            targets_by_city.setdefault(city_norm, []).append(li)
        if city_norm in SEVERE_ENDPOINTS:
            severe_targets_by_city.setdefault(city_norm, []).append(li)

    if not targets_by_city and not severe_targets_by_city:
        log.info("code_enf.no_targets")
        return

    sem = asyncio.Semaphore(4)
    counts = {"queried": 0, "tagged": 0, "violations_found": 0,
              "severe_queried": 0, "severe_tagged": 0}

    async def one(li: Listing, cfg: dict) -> None:
        async with sem:
            feats = await _fetch_violations_for_listing(c, li, cfg)
            counts["queried"] += 1
            if feats is None:
                return                       # could not ask: leave whatever is there
            if not feats:
                _clear_stale_block(li, counts)
                return
            real_hits = _proximity_filter(li, feats)
            if not real_hits:
                _clear_stale_block(li, counts)
                return

            counts["violations_found"] += len(real_hits)
            counts["tagged"] += 1

            # Aggregate
            violations = []
            statuses = set()
            for f in real_hits[:5]:
                attrs = f.get("attributes", {}) or {}
                v = _pick(attrs, cfg["violation_fields"]) or "unknown"
                s = _pick(attrs, cfg["status_fields"]) or "unknown"
                d = _pick(attrs, cfg["date_fields"])
                statuses.add(s.lower())
                violations.append({
                    "violation": v[:200],
                    "status": s,
                    "date": str(d)[:10] if d else None,
                })

            if not isinstance(li.raw, dict):
                li.raw = {}
            block = {
                "city": li.city,
                "open_violations": len([v for v in violations
                                        if not _is_closed_status(v["status"])]),
                "total_violations": len(real_hits),
                "violations": violations,
                "has_open": any(not _is_closed_status(s) for s in statuses),
                "source": _SOURCE_TAG,
            }
            li.raw["code_enforcement"] = stamp(block, ttl_days=_TTL_DAYS)

    async def severe_one(li: Listing, cfg: dict) -> None:
        """A standing order to demolish outranks an ordinary open-violation case, so
        it is checked separately and merged in as a `severity` marker on whatever
        code_enforcement block already exists (building a minimal one if this city
        isn't also in CITY_ENDPOINTS) rather than overwriting it. A miss here means
        "no demolish order on file" -- NOT "no violations" -- so it never clears an
        existing block the regular pass (or another producer) already wrote."""
        async with sem:
            feats = await _fetch_violations_for_listing(c, li, cfg)
            counts["severe_queried"] += 1
            if not feats:
                return
            real_hits = _proximity_filter(li, feats)
            if not real_hits:
                return
            if not isinstance(li.raw, dict):
                li.raw = {}
            ce = li.raw.get("code_enforcement")
            if not isinstance(ce, dict):
                ce = {"city": li.city, "open_violations": 0, "total_violations": 0,
                      "violations": [], "has_open": False, "source": _SOURCE_TAG}
            ce["severity"] = cfg["severity"]
            ce["has_open"] = True
            li.raw["code_enforcement"] = stamp(ce, ttl_days=_TTL_DAYS)
            counts["severe_tagged"] += 1

    async with client(timeout=20.0) as c:
        for city, lis in targets_by_city.items():
            cfg = CITY_ENDPOINTS[city]
            log.info("code_enf.city_start", city=city, target_count=len(lis))
            await asyncio.gather(*(one(li, cfg) for li in lis))
        for city, lis in severe_targets_by_city.items():
            cfg = SEVERE_ENDPOINTS[city]
            log.info("code_enf.severe_city_start", city=city, target_count=len(lis))
            await asyncio.gather(*(severe_one(li, cfg) for li in lis))

    log.info("code_enf.done", **counts)
