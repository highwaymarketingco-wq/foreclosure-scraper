"""Wake County NC code cases opened in the last 90 days (published by Wake County on the
Raleigh/Wake open-data portal).

SOURCE
    services1.arcgis.com/a7CWfuGP5ZnLYE7I .../codecases_90days_test/FeatureServer/0 (owner
    WakeCountyGovernment's org; the service name says "test" but it is the published layer and
    was edited 2026-10-07). 575 cases on 2026-10-07, a rolling 90-day window: Zebulon 392, Wake
    County unincorporated 89, Wendell 44, Raleigh 21 and a few each in other towns. This
    overturns the 2026-09-28 note that Wake had nothing live.

WHAT IS READ
    OPEN cases only (CASE_STATUS 'In Progress', 'Escalated', 'Escalated to Code Case'; the
    'Closed - ...' and 'Void' states are resolved), and of those:
      * 'VIO - Building Inspections' (fire-damaged buildings, collapses, unsafe repairs) and
        'VIO - Wastewater' (failed septic systems, a habitability problem), all admitted;
      * 'VIO - Planning/Zoning' and town-ordinance cases only when the description names a
        structural problem (fire, damage, collapse, unsafe, dilapidated, condemned, vacant,
        abandoned); weeds, trash, junk vehicles and home businesses are not distress.
    DESCRIPTION is free text that sometimes names a person or a business, so it is NEVER stored:
    only the category it was matched to is kept.

DATELESS: slug counties_nc.wake_code_cases goes in main.DATELESS_OK_SOURCES.
Gate: FORECLOSURE_WAKE_CODE=0.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ..counties_generic._layer_kit import clean, fetch_attrs

log = structlog.get_logger()

SLUG = "counties_nc.wake_code_cases"
ENV_OFF = "FORECLOSURE_WAKE_CODE"
LAYER = ("https://services1.arcgis.com/a7CWfuGP5ZnLYE7I/arcgis/rest/services/"
         "codecases_90days_test/FeatureServer/0")
PAGE = "https://data-ral.opendata.arcgis.com/"

FIELDS = ("CASE_NUMBER", "OPENED_DATE", "DISTRICT", "CASE_STATUS", "CASE_TYPE", "DESCRIPTION",
          "STREET_ADDRESS", "CITY_STATE_ZIP")
OPEN_STATUSES = ("In Progress", "Escalated", "Escalated to Code Case")
ALWAYS = ("VIO - Building Inspections", "VIO - Wastewater")

#: Wording that names a department, a report or a form, not the property's condition: 4 of 30
#: sampled rows on 10/8 were tagged unsafe from the boilerplate "code violations or life safety
#: issues" of a site-visit referral, or fire_damage from "fire services report" / a fire-marshal
#: referral (audit 2026-10-09 additions_verify).
_BOILERPLATE = re.compile(r"code violations? or life safety issues?|"
                          r"\bfire\s+(?:services?|marshal'?s?|department|dept\.?|inspector|prevention|"
                          r"code|referral|report)\b", re.I)

_STRUCT = {
    "fire_damage": re.compile(r"\bfire\b|burn", re.I),
    "collapse": re.compile(r"collap", re.I),
    "unsafe": re.compile(r"unsafe|hazard|life safety|dangerous", re.I),
    "dilapidated": re.compile(r"dilapidat|deteriorat|condemn|uninhabit|unfit", re.I),
    "vacant": re.compile(r"vacant|abandon|boarded", re.I),
    "septic_failure": re.compile(r"septic|wastewater|malfunction|o&m|failure", re.I),
    "repair": re.compile(r"repair", re.I),
}
_SEVERE = {"fire_damage", "collapse", "unsafe", "dilapidated", "vacant"}
_REQUEST = re.compile(r"repair request|real estate transaction", re.I)

WHERE = "CASE_STATUS IN ({})".format(",".join(f"'{s}'" for s in OPEN_STATUSES))


def classify(case_type: Optional[str], description: Optional[str]) -> Optional[list[str]]:
    """The structural categories a case belongs to, or None when it is not distress."""
    text = _BOILERPLATE.sub(" ", description or "")
    tags = [k for k, rx in _STRUCT.items() if rx.search(text)]
    if _REQUEST.search(description or "") and not set(tags) & _SEVERE:
        return None      # an owner's / contractor's own repair-inspection request, not a violation
    if (case_type or "") in ALWAYS:
        if case_type == "VIO - Wastewater" and "septic_failure" not in tags:
            tags.append("septic_failure")
        return tags or ["building_inspection"]
    return tags if set(tags) & _SEVERE else None


def _city_zip(v: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    m = re.match(r"^\s*(.*?)[,\s]+NC\s+(\d{5})", v or "", re.I)
    return (m.group(1).title(), m.group(2)) if m else (clean(v), None)


def to_listing(a: dict, *, now: Optional[datetime] = None) -> Optional[Listing]:
    if clean(a.get("CASE_STATUS")) not in OPEN_STATUSES:
        return None
    tags = classify(clean(a.get("CASE_TYPE")), a.get("DESCRIPTION"))
    street = clean(a.get("STREET_ADDRESS"))
    if not tags or not street:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        opened = datetime.fromtimestamp(int(a.get("OPENED_DATE")) / 1000, tz=timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        opened = None
    city, zip_ = _city_zip(a.get("CITY_STATE_ZIP"))
    severe = bool(set(tags) & _SEVERE) or clean(a.get("CASE_TYPE")) == "VIO - Building Inspections"
    raw: dict[str, Any] = {
        "wake_code_case": {"case": clean(a.get("CASE_NUMBER")), "type": clean(a.get("CASE_TYPE")),
                           "status": clean(a.get("CASE_STATUS")), "district": clean(a.get("DISTRICT")),
                           "opened": opened.isoformat() if opened else None, "categories": tags},
        "code_enforcement": {
            "county": "Wake", "open_violations": 1, "total_violations": 1, "prior_cases": 0,
            "repeat_offender": False, "violation_types": tags, "severe": severe,
            "violations": [{"violation": "/".join(tags), "status": "open",
                            "date": opened.isoformat() if opened else None,
                            "case_id": clean(a.get("CASE_NUMBER"))}],
            "has_open": True, "vacancy_adjacent": severe, "source": SLUG,
            "stamped_at": now.date().isoformat(),
            "stale_after": ((opened or now.date()) + timedelta(days=365)).isoformat(),
        },
    }
    if severe:
        raw["distressed"] = True
    return Listing(
        source=SLUG, source_url=PAGE,
        listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Wake", street_address=street, city=city, zip_code=zip_,
        foreclosure_process="code_enforcement",
        description=f"Wake NC open code case ({'/'.join(tags)}) — {street}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class WakeCodeCases(BaseScraper):
    slug = SLUG
    name = "Wake County NC open code cases, last 90 days"
    category = "county_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        async with client(timeout=60.0) as c:
            rows = await fetch_attrs(c, LAYER, FIELDS, where=WHERE)
        out = [li for li in (to_listing(a) for a in rows) if li]
        log.info("wake_code.done", open_cases=len(rows), leads=len(out))
        return out
