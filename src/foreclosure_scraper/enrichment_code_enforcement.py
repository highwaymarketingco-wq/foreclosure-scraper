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
from typing import Optional

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
            r = await c.get(cfg["url"], params=params, timeout=15.0)
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


def _clear_stale_block(li: Listing, counts: dict) -> None:
    """The city answered and has no case at this address. Drop a block THIS enricher wrote on
    an earlier run; leave one a county scraper or another enricher wrote (different source)."""
    ce = li.raw.get("code_enforcement") if isinstance(li.raw, dict) else None
    if isinstance(ce, dict) and ce.get("source") == _SOURCE_TAG:
        li.raw.pop("code_enforcement", None)
        counts["cleared"] = counts.get("cleared", 0) + 1


async def enrich_with_code_enforcement(listings: list[Listing]) -> None:
    """For each listing in a covered city, look up open code-enforcement
    violations. Tag matched listings with the count + worst-severity violation.
    """
    if not listings:
        return

    # City detection by city name (case-insensitive)
    targets_by_city: dict[str, list[Listing]] = {}
    for li in listings:
        if not li.city:
            continue
        city_norm = li.city.strip().title()
        if city_norm in CITY_ENDPOINTS:
            targets_by_city.setdefault(city_norm, []).append(li)

    if not targets_by_city:
        log.info("code_enf.no_targets")
        return

    sem = asyncio.Semaphore(4)
    counts = {"queried": 0, "tagged": 0, "violations_found": 0}

    async def one(li: Listing, cfg: dict) -> None:
        async with sem:
            feats = await _fetch_violations_for_listing(c, li, cfg)
            counts["queried"] += 1
            if feats is None:
                return                       # could not ask: leave whatever is there
            if not feats:
                _clear_stale_block(li, counts)
                return
            # Verify by lat/lng proximity if listing has coords
            real_hits: list[dict] = []
            if li.latitude and li.longitude:
                for f in feats:
                    geom = f.get("geometry") or {}
                    glat, glon = geom.get("y"), geom.get("x")
                    if glat is None or glon is None:
                        continue
                    d = _haversine_miles(float(li.latitude), float(li.longitude),
                                         float(glat), float(glon))
                    if d <= 0.05:  # 0.05 mile = ~250 ft
                        real_hits.append(f)
            else:
                real_hits = feats

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
                                        if v["status"].lower() not in ("closed", "resolved")]),
                "total_violations": len(real_hits),
                "violations": violations,
                "has_open": any(s not in ("closed", "resolved") for s in statuses),
                "source": _SOURCE_TAG,
            }
            li.raw["code_enforcement"] = stamp(block, ttl_days=_TTL_DAYS)

    async with client(timeout=20.0) as c:
        for city, lis in targets_by_city.items():
            cfg = CITY_ENDPOINTS[city]
            log.info("code_enf.city_start", city=city, target_count=len(lis))
            await asyncio.gather(*(one(li, cfg) for li in lis))

    log.info("code_enf.done", **counts)
