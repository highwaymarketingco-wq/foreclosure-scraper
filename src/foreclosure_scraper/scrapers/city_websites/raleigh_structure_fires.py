"""City of Raleigh NC structure fires: buildings that burned, from the city's own open data.

SOURCE
    Raleigh Open Data "Fire Incidents" (owner ``OpenData_ral``), hosted layer
    ``Fire_Incidents_Public/FeatureServer/0``. Every Raleigh Fire Department incident with
    its type and street address, refreshed daily (last edit 2026-10-07, 323,778 rows back
    to 2004). Nothing in this repo read it before 2026-10-07, and no other source in the
    repo carries fire damage at all.

    Raleigh switched from NFIRS to NERIS in January 2026, and the layer shows it:
    2025 rows carry an NFIRS ``incident_type`` (111 Building fire: 210 in 2025), 2026 rows
    carry a NERIS ``incident_type_name`` instead ("Structural Involvement" 83, "Room and
    Contents Fire" 54, "Building Collapse / Structure Collapse" 5, January to early
    October 2026). Both vocabularies are filtered server-side; cooking fires confined to a
    pan, chimney fires, vehicle, brush and rubbish fires are left out because they do not
    damage the building.

    Roughly 150 to 210 serious structure fires a year. A burned house is one of the
    strongest as-is seller situations there is and has had no source here.

ROW SHAPE
    One lead per address (repeat calls to the same building fold into one, newest first).
    The address arrives as "123 MAIN ST RALEIGH, NC 27603"; the street, city and ZIP are
    split out. No owner or parcel on the layer: the address resolver supplies them, the
    same way the Columbia and Durham code layers work.
    raw["fire_incident"] holds the incident numbers, dates and types; raw["distressed"]
    marks physical damage for the scorer.

    The newer NERIS layer at FSRI is NOT used: its terms forbid automated access and
    commercial use (see docs/new_sources_2026-10-07_distress.md). This city layer is the
    city's own publication.

DATELESS: ships under the ``counties_generic.arcgis_distress.`` prefix that
``main.DATELESS_OK_SOURCES`` already admits (see ``_layer_kit``).
Gate: ``FORECLOSURE_RALEIGH_FIRES=0``. Window: ``FORECLOSURE_RALEIGH_FIRES_DAYS`` (730).
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
from ..counties_generic._layer_kit import DATELESS_PREFIX, clean, fetch_attrs

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_RALEIGH_FIRES"
ENV_DAYS = "FORECLOSURE_RALEIGH_FIRES_DAYS"
SLUG = "city_websites.raleigh_structure_fires"
SOURCE = DATELESS_PREFIX + "raleigh_structure_fires"

LAYER = ("https://services.arcgis.com/v400IkDOw1ad7Yad/arcgis/rest/services/"
         "Fire_Incidents_Public/FeatureServer/0")
PAGE_URL = "https://data-ral.opendata.arcgis.com/"

FIELDS = (
    "incident_number", "incident_type", "incident_type_description",
    "incident_group_name", "incident_subgroup_code", "incident_type_name",
    "dispatch_date_time", "exposure", "address",
)

#: NFIRS 111 Building fire, 112 Fire in a structure other than a building.
NFIRS_TYPES = (111, 112)
#: NERIS incident types (2026 onward) that mean the building itself burned or failed.
NERIS_TYPES = ("Structural Involvement", "Room and Contents Fire",
               "Building Collapse / Structure Collapse")


def where_clause(since: datetime) -> str:
    neris = ",".join("'" + t.replace("'", "''") + "'" for t in NERIS_TYPES)
    nfirs = ",".join(str(t) for t in NFIRS_TYPES)
    return (f"dispatch_date_time >= DATE '{since:%Y-%m-%d}' AND "
            f"(incident_type IN ({nfirs}) OR incident_type_name IN ({neris}))")


_ADDR_RE = re.compile(r"^\s*(?P<street>.+?)\s*,\s*(?P<st>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?\s*$", re.I)
#: Place names that end the street part ("... RD RALEIGH, NC 27615").
_CITIES = ("RALEIGH", "GARNER", "CARY", "KNIGHTDALE", "WAKE FOREST", "ROLESVILLE",
           "MORRISVILLE", "APEX", "DURHAM", "WENDELL", "ZEBULON", "HOLLY SPRINGS",
           "FUQUAY VARINA", "FUQUAY-VARINA", "CREEDMOOR", "YOUNGSVILLE")
_CITY_RE = re.compile(r"^(?P<street>.*?)\s+(?P<city>" + "|".join(
    re.escape(c) for c in sorted(_CITIES, key=len, reverse=True)) + r")$", re.I)


def split_address(addr: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'123 MAIN ST RALEIGH, NC 27603' -> ('123 MAIN ST', 'Raleigh', '27603')."""
    s = clean(addr)
    if not s:
        return None, None, None
    m = _ADDR_RE.match(s)
    if not m:
        return s, None, None
    street, zip_ = m.group("street"), m.group("zip")
    cm = _CITY_RE.match(street)
    if cm and cm.group("street"):
        return cm.group("street").strip(), cm.group("city").title(), zip_
    return street, None, zip_


def _epoch_ms(v: Any) -> Optional[datetime]:
    """The layer stores dispatch times in UTC (dateFieldsTimeReference UTC); the fire happened on
    the LOCAL (Eastern) date: an evening dispatch read as UTC landed on the next day (2 of 30
    sampled rows on 10/8; audit 2026-10-09 additions_verify)."""
    try:
        utc = datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 - no tz database: keep UTC rather than lose the date
        return utc.replace(tzinfo=None)


def _type_label(a: dict) -> Optional[str]:
    return clean(a.get("incident_type_name")) or clean(a.get("incident_type_description"))


def fold(rows: Iterable[dict]) -> list[dict]:
    """One group per street address, incidents newest first."""
    groups: dict[str, dict] = {}
    for a in rows:
        street, city, zip_ = split_address(a.get("address"))
        if not street or not re.match(r"^\d", street):
            continue            # an intersection or a blank: no building to point at
        k = f"{street.lower()}|{zip_ or ''}"
        g = groups.setdefault(k, {"street": street, "city": city, "zip": zip_, "incidents": []})
        g["incidents"].append({
            "incident_number": clean(a.get("incident_number")),
            "date": _epoch_ms(a.get("dispatch_date_time")),
            "type": _type_label(a),
            "nfirs_type": a.get("incident_type"),
            "exposure": a.get("exposure"),
        })
    for g in groups.values():
        g["incidents"].sort(key=lambda i: i["date"] or datetime.min, reverse=True)
    return list(groups.values())


def to_listing(g: dict, *, now: Optional[datetime] = None) -> Listing:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    inc = g["incidents"]
    latest = inc[0]
    when = latest["date"].strftime("%Y-%m-%d") if latest["date"] else "date unknown"
    raw = {
        "fire_incident": {
            "count": len(inc),
            "latest_date": when,
            "latest_type": latest["type"],
            "incidents": [{**i, "date": i["date"].isoformat() if i["date"] else None}
                          for i in inc[:10]],
            "source": "raleigh_open_data_fire_incidents",
        },
        "distressed": True,
    }
    return Listing(
        source=SOURCE,
        source_url=PAGE_URL,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Wake",
        street_address=g["street"],
        city=g["city"] or "Raleigh",
        zip_code=g["zip"],
        foreclosure_process="fire_damage",
        description=f"Raleigh structure fire {when}: {latest['type'] or 'building fire'}"
                    f"{f' ({len(inc)} incidents)' if len(inc) > 1 else ''} — {g['street']}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class RaleighStructureFires(BaseScraper):
    slug = SLUG
    name = "City of Raleigh structure fires (Raleigh Open Data fire incidents)"
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
        async with client(timeout=60.0) as c:
            rows = await fetch_attrs(c, LAYER, FIELDS, where=where_clause(since))
        out = [to_listing(g) for g in fold(rows)]
        log.info("raleigh_fires.done", incidents=len(rows), leads=len(out))
        return out
