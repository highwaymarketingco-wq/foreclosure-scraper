"""City of Asheville NC — Accela code-enforcement cases (AccelaServicesView).

WHY THIS EXISTS, AND WHY IT SHIPS DISABLED (2026-10-03 reconnaissance)
    Asheville's own ArcGIS Server self-hosts a flattened view of its Accela
    permitting/code-enforcement backend:

        https://gis.ashevillenc.gov/server/rest/services/Permits/
        AccelaServicesView/MapServer/0

    This was wired into `enrichment_code_enforcement.py` as a MATCH-ONLY
    enricher on 2026-07-01 (commit `311ba4fc`) on the strength of "HTTP 200,
    real addressed cases" -- 2,738 rows, never a dead end. A follow-up sweep
    on 2026-10-02 (commit `6e00d55b`) re-confirmed the same 2,738-row count
    and flagged it as a real, live, buildable standalone LEAD source worth
    ~1,000 rows after category filtering, scoped for its own reconnaissance
    pass -- this file is that pass.

    **The reconnaissance found the premise was wrong.** Nobody had ever
    checked the DATES. Live-queried today via `outStatistics` MIN/MAX against
    the real service:

        date_opened        min 2016-01-04  max 2018-12-14
        date_statused       -                max 2018-12-14
        date_closed          -                max 2018-12-14
        record_status_date   -                max 2018-12-14
        date_assigned         -                max 2017-05-24  (oldest-maxing field)

    Every one of those is the OVERALL max across all 2,738 rows -- not a
    per-category figure. Repeated per `record_type_category` (Housing Code
    Referral, Junked Vehicles, Damage - Incident, FMO Referral, Stop Work
    Order, Other Referral, Short Term Rental, Land Use, Sign Violation):
    every single category's own date_opened max also falls inside
    2016-01 .. 2018-12-14. There is no slice of this table newer than
    2018-12-14. Sampled "still open" statuses (`Open` 68, `NOV Mailed` 41,
    `NOV Served` 50, `Citation Pending` 32, `Unsafe Structure` 5,
    `Deteriorated Structure` 13, `Monitor` 13, ...) all have their OWN
    `record_status_date` frozen at the same ~2018 ceiling -- there is no way
    to tell whether any of them are still open today. The entire table is a
    dead snapshot, not a renewing feed: Accela's sync into this ArcGIS view
    appears to have stopped running after 2018-12-14 and nothing replaced it
    (consistent with `city_websites/asheville_min_housing.py`'s independent
    2026-09-15 finding that Asheville's current minimum-housing process
    publishes no public case registry anywhere on its own website).

    Presenting an 8-10-year-old "open" code case as a current motivated-
    seller signal would be actively misleading, not merely low-value -- the
    same failure shape `city_websites/charlotte_open_data.py`'s own docstring
    already names and rejects for a different stale Mecklenburg layer
    ("issuedate/compldate both max out at April 2017 -- stale, not a current
    feed. Dropped rather than land dead data."). Per the standing instruction
    to report a messier-than-expected finding honestly rather than force
    something fragile into the registry: **this module is NOT wired into the
    scraper it could otherwise be.** `fetch()` runs one cheap live
    `outStatistics` MAX(date_opened) probe every call and returns `[]`
    whenever the feed is still frozen (`_STALE_AFTER_DAYS`) -- a real,
    testable, self-healing gate, not a hardcoded disable someone has to
    remember to revisit. If Asheville ever resumes syncing this view (or
    points it at a successor system), this scraper starts producing real
    rows on its own, with no human intervention, the next time it runs.

    The companion fix for the OTHER half of this investigation -- the
    now-confirmed-stale `enrichment_code_enforcement.py` "Asheville"
    match-only entry, which was tagging today's real Asheville leads with
    false `has_open` credit off this same dead table -- has been removed
    there; see that module's docstring.

CATEGORY TAXONOMY (live-verified 2026-10-03, NOT Henderson's or Gastonia's
vocabulary -- Accela's own `record_type_category` field, cross-checked
against real `description` text per case, same discipline as both of those
modules)
    `record_type_category` breakdown of all 2,738 rows (`record_type_type`
    'Complaint-Enforcement' is the actual code-enforcement half; 'Project
    Inquiry'/'Continuing Education' are unrelated permitting/training
    records that happen to live in the same view and are excluded by the
    category allowlist below, not by `record_type_type`, since a handful of
    genuine enforcement rows carry an uncoded 'NA' category):

      Short Term Rental    723  "ZOE: Short Term Rental" -- zoning complaints
                               about unpermitted homestays/Airbnbs. Sampled:
                               "Short Term Rental prohibited / unpermitted
                               homestay" x3. Regulatory, not a property-
                               condition signal. NOT severe.
      Other Referral       248  Mostly "ZOE: Other" -- landscaping/zoning
                               trivia (excessive pruning, fence height, LED
                               window lights, handrail not per plan). One
                               sampled case ("Res: Enforcement Case", 110
                               Swannanoa River Rd) reads "Empty residence
                               unsecured, occupied by vagrants" -- genuinely
                               severe -- but it is one hit in a category
                               that is 95%+ zoning/landscaping noise, the
                               same shape Henderson's "General" and
                               Gastonia's "Vegetation/Weeds" were excluded
                               for. NOT severe at the category level.
      Sign Violation        144  Signage. NOT severe (same reasoning as every
                               sibling module's Sign/Signage exclusion).
      Junked Vehicles       127  "complaint stated there were 4 or 5 junk
                               cars", "junk car with expired tag" -- textbook
                               junk-vehicle blight, same category Henderson/
                               Gastonia both already treat as severe. SEVERE.
      Stop Work Order        86  "SWO NO PERMITS... Demolition and some
                               reconstruction without permits", "built a
                               deck, poured footings... without permits" --
                               active, unpermitted CONSTRUCTION/renovation.
                               This is the opposite signal from vacancy: an
                               owner actively investing in the structure,
                               just without a permit. NOT severe.
      Land Use               79  Home occupation, accessory structure
                               without a permit, pool placement, a business
                               run from a residence, a missing site plan --
                               paperwork/zoning, not property condition
                               (same bucket as Henderson's Zoning / Gaston's
                               Zoning-Land Use). NOT severe.
      Damage - Incident      72  Real structural-damage incidents: a tree
                               through a roof ("owner advised not to stay in
                               the home"), an apartment-building fire
                               ("entire building vacated... all utilities
                               disconnected"), house fires ("ALL UTILITIES
                               HAVE BEEN DISCONNECTED"), a vehicle strike on
                               a building. These describe a structure made
                               uninhabitable by a casualty event, often with
                               utilities cut and occupants displaced --
                               genuinely vacancy-adjacent, the same concept
                               as a standing order to demolish just not yet
                               formalized as one. SEVERE.
      Housing Code Referral  69  "house doe not have power or water
                               service", "individuals are living in the
                               residence with no utilities", "MHC
                               [Minimum Housing Code] complaint" -- direct
                               habitability/occupancy-without-utilities
                               complaints. SEVERE.
      FMO Referral           32  Fire Marshal's Office coordination: a
                               carpet/display-wall permit, an occupancy/
                               construction permit handoff between two
                               connected retail spaces, a temporary movie-
                               production space-use permit. Despite the
                               "enforcement"-sounding name, every sampled
                               case is routine business-use/permit paperwork
                               routed through the fire marshal, not a fire-
                               code violation on a distressed structure.
                               NOT severe.

    `_SEVERE_CATEGORIES` below encodes exactly the 3 confirmed-severe rows
    (Housing Code Referral, Junked Vehicles, Damage - Incident) =
    69 + 127 + 72 = **268** of 2,738 (9.8%) -- matching
    `docs/enumeration_r2/r2_municipal_NC_West.md`'s independent 2026 count of
    "268 addressed distress cases" almost exactly, confirming the category
    counts themselves are stable and real; it is the DATES underneath them
    that make the whole table unusable as a current source.

WHAT THE API ACTUALLY RETURNS (confirmed live 2026-10-03)
    No owner name field of any kind -- the service's own field list (`?f=json`
    on the layer) has no `owner`/`applicant`/`contact` column. Identifying
    data is address (`address`, a single free-text "123 MAIN ST, ASHEVILLE,
    NC 28801" string), `parcel_number` and `apn` (identical values on every
    sampled row -- Buncombe County PINs, 5-6 digit legacy format, e.g.
    "16095"), and `business_name`/`license_number` on the business-permit
    side of the table (not populated on the code-enforcement categories
    above). `description` (4000 chars) carries the inspector's free-text
    narrative -- frequently a forwarded staff email thread with city
    employee names/addresses inline (@ashevillenc.gov), never a private
    citizen's contact info. `record_comments` (50000 chars) is deliberately
    NOT requested here -- an internal case-log field this wide is exactly
    the shape of column this repo's own PII discipline
    (`docs/enumeration_r2/r2_municipal_NC_West.md`'s Fletcher/Hendersonville
    findings) says to leave alone rather than pull with a blanket `outFields`.

Free, public, anonymous ArcGIS REST (gis.ashevillenc.gov), no auth, no CAPTCHA.
Dateless (a code case has no sale date) -> routed via DATELESS_OK_SOURCES, same
as every sibling in this family, so a future revival is not silently dropped by
`_active_only()` the first time it actually emits a row.
Gate with FORECLOSURE_ASHEVILLE_CODE=0 (on top of the staleness self-gate).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_ASHEVILLE_CODE"

LAYER = ("https://gis.ashevillenc.gov/server/rest/services/Permits/"
         "AccelaServicesView/MapServer/0")

#: The human-facing page this layer backs no case search UI for (see module
#: docstring) -- carried only as the Listing's source_url.
DASHBOARD_URL = "https://www.ashevillenc.gov/department/development-services/"

_FIELDS = ("record_id", "address", "record_status", "record_status_date",
           "record_type", "record_type_category", "description",
           "short_notes", "date_opened", "parcel_number", "apn")
_OUT_FIELDS = ",".join(_FIELDS)

#: record_type_category values confirmed live 2026-10-03 (via real sampled
#: `description` text, not the bare label) to describe physical property
#: condition/habitability rather than paperwork, permitting, signage, or
#: zoning. See the module docstring's full category breakdown for the
#: evidence behind each inclusion/exclusion.
_SEVERE_CATEGORIES = frozenset({
    "Housing Code Referral",
    "Junked Vehicles",
    "Damage - Incident",
})

#: Status text containing this (case-insensitive) closes a case out -- same
#: negative-match convention as henderson_code_violations.py/
#: gastonia_code_enforcement.py, so a status this feed adds later defaults to
#: OPEN (visible) rather than silently invisible.
_CLOSED_RE = re.compile(r"closed", re.I)

#: If the live feed's own MAX(date_opened) is older than this, the table is
#: the same frozen 2016-2018 snapshot this reconnaissance found -- skip the
#: crawl entirely rather than emit any row from it. Generous (>1 year) so an
#: ordinary slow news month at a small city department does not trip it;
#: tight enough that a genuinely abandoned feed cannot coast through.
_STALE_AFTER_DAYS = 400

_PAGE = 1000


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _epoch_to_dt(v: Any) -> datetime | None:
    """ArcGIS dates are epoch milliseconds (UTC)."""
    if v in (None, "", " "):
        return None
    try:
        return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _iso(v: Any) -> str | None:
    dt = _epoch_to_dt(v)
    return dt.date().isoformat() if dt else None


def is_closed(status: Any) -> bool:
    return bool(_CLOSED_RE.search(str(status or "")))


def is_severe(category: Any) -> bool:
    return str(category or "").strip() in _SEVERE_CATEGORIES


async def max_date_opened(http) -> datetime | None:
    """The live feed's own overall MAX(date_opened) -- the staleness probe.

    One lightweight `outStatistics` call, no feature rows. Raises
    ``agw.ArcGisError`` on a genuine service error so a transient outage
    reads as an ERROR, not as "confirmed frozen."
    """
    rows = await agw.query_attributes(
        http, LAYER, where="1=1", out_fields="objectid",
        extra={"outStatistics": (
            '[{"statisticType":"max","onStatisticField":"date_opened",'
            '"outStatisticFieldName":"mx"}]')},
        page=1, max_records=1)
    if not rows:
        return None
    return _epoch_to_dt(rows[0].get("mx"))


def build_listing(attrs: dict, now: datetime | None = None) -> Listing | None:
    """One Accela case -> one Listing, OPEN cases only (matches Henderson's
    query-time filter / Gastonia's open_count==0 check -- a closed case is
    not a live lead). No PIN-join / grouping pass here -- unlike Henderson/
    Gastonia there is no owner field at all, so every case stands alone at
    its address (still joins the board's dedupe key via `parcel_id` when
    that lines up with the county's own PIN format)."""
    now = now or datetime.utcnow()
    status = _clean(attrs.get("record_status")) or "unknown"
    if is_closed(status):
        return None

    address = _clean(attrs.get("address"))
    pin = _clean(attrs.get("parcel_number")) or _clean(attrs.get("apn"))
    if not address and not pin:
        return None

    category = _clean(attrs.get("record_type_category"))
    severe = is_severe(category)

    raw: dict[str, Any] = {
        # Same shape henderson_code_violations.py / gastonia_code_enforcement.py
        # write, so distress_score.py's PROPERTY signal and every downstream
        # reader works as-is.
        "code_enforcement": {
            "county": "Buncombe",
            "city": "Asheville",
            "open_violations": 1,
            "total_violations": 1,
            "repeat_offender": False,
            "violation_types": [category] if category else [],
            "severe": severe,
            "violations": [{
                "violation": category or _clean(attrs.get("record_type")) or "unknown",
                "status": status,
                "date": _iso(attrs.get("date_opened")),
                "case_id": _clean(attrs.get("record_id")),
            }],
            "has_open": True,
            "vacancy_adjacent": severe,
            "opened": _iso(attrs.get("date_opened")),
            "source": "asheville_accela_services_view",
        },
    }
    if severe:
        raw["distressed"] = True

    desc = (f"Open Asheville code case ({category or 'uncategorized'})"
            + (f" — {_clean(attrs.get('description'))[:160]}"
               if _clean(attrs.get("description")) else ""))

    return Listing(
        source=AshevilleCodeEnforcement.slug,
        source_url=DASHBOARD_URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        city="Asheville",
        street_address=address,
        parcel_id=pin,
        sale_date=None,
        case_number=_clean(attrs.get("record_id")),
        description=desc,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class AshevilleCodeEnforcement(BaseScraper):
    slug = "counties_nc.asheville_code_enforcement"
    name = "City of Asheville NC Accela Code Enforcement (AccelaServicesView)"
    category = "code_enforcement"
    expected_min_count = 0
    timeout_s = 180.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("asheville_code.disabled")
            return []

        async with client(timeout=45.0) as http:
            mx = await max_date_opened(http)
            if mx is None:
                log.warning("asheville_code.no_date_signal")
                return []
            age_days = (datetime.utcnow() - mx).days
            if age_days > _STALE_AFTER_DAYS:
                # Confirmed 2026-10-03: the whole table is a dead 2016-2018
                # snapshot. See the module docstring. Self-healing: this check
                # re-runs live every call, so a resumed feed starts producing
                # again with no code change.
                log.warning("asheville_code.frozen_feed_skipped",
                            max_date_opened=mx.date().isoformat(), age_days=age_days,
                            threshold_days=_STALE_AFTER_DAYS)
                return []

            cats = ",".join("'" + c.replace("'", "''") + "'" for c in _SEVERE_CATEGORIES)
            attrs_list = await agw.query_attributes(
                http, LAYER, where=f"record_type_category IN ({cats})",
                out_fields=_OUT_FIELDS, page=_PAGE, max_records=20000)

        now = datetime.utcnow()
        out: list[Listing] = []
        for attrs in attrs_list:
            li = build_listing(attrs, now=now)
            if li:
                out.append(li)
        log.info("asheville_code.parsed", raw=len(attrs_list), listings=len(out),
                 severe=sum(1 for li in out if (li.raw or {}).get("distressed")))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = AshevilleCodeEnforcement()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        for li in rows[:15]:
            ce = li.raw["code_enforcement"]
            print(f"  pin={li.parcel_id or '-':10} open={ce['has_open']} "
                  f"{','.join(ce['violation_types'])[:26]:26} {(li.street_address or '')[:34]}")

    asyncio.run(_main())
