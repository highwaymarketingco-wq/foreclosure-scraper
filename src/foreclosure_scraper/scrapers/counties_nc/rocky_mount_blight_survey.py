"""Rocky Mount NC 2025 parcel condition survey: dilapidated, deteriorated and
vacant-and-boarded parcels, Nash and Edgecombe counties.

SOURCE
    Six public hosted layers published under project number 25002586A ("Rocky Mount")
    by the city's planning consultant (owner ``tpursley_colliersgis``, tagged
    "dilapidated"). Found 2026-10-07 by an ArcGIS Online search over the NC/SC extent;
    nothing in this repo read them before. Each layer is a subset of the NC OneMap parcel
    schema (PARNO, OWNNAME, MAILADD/MCITY/MSTATE/MZIP, SITEADD/SCITY/SZIP, PARVAL ...)
    for the parcels the survey put in that class. Live counts on 2026-10-07:

        Edgecombe dilapidated 124   Nash dilapidated 92
        Edgecombe deteriorated 147  Nash deteriorated 64
        Edgecombe vacant+boarded 139  Nash vacant+boarded 85

    (651 rows; a parcel can sit in more than one class, so rows are folded by county and
    parcel.) The data edits are dated 2025-06/07; it is a one-time 2025 survey, not a feed,
    so treat it as a 2025 snapshot and re-check the service each quarter.

SIGNALS (shapes the scorer already reads; no new key invented)
    dilapidated     raw["condemned"] = True. The same bare flag ``greenwood_cama_condemned``
                    uses for an appraiser's "Worn Out" rating: a structure a surveyor
                    judged beyond ordinary repair.
    deteriorated    raw["distressed"] = True (physical condition, not a tax fact).
    vacant_boarded  raw["vacancy"] = {"vacant": True, "boarded_up": True, ...}, the
                    Hendersonville register's shape.
    Owner mailing goes to raw["owner_mailing"] (absentee / out-of-state).

DATELESS
    No sale date exists, so rows ship under the ``counties_generic.arcgis_distress.``
    family prefix that ``main.DATELESS_OK_SOURCES`` already admits (see ``_layer_kit``).

PRIVACY: explicit outFields (property-record columns only), ``drop_sensitive`` on every
attribute bag. Gate: ``FORECLOSURE_ROCKY_MOUNT_BLIGHT=0``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind
from ..counties_generic._layer_kit import DATELESS_PREFIX, clean, fetch_attrs, num, owner_mailing

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_ROCKY_MOUNT_BLIGHT"
SLUG = "counties_nc.rocky_mount_blight_survey"
SOURCE = DATELESS_PREFIX + "rocky_mount_blight_survey_2025"

_BASE = "https://services.arcgis.com/mmindpmdbSZXPVNc/arcgis/rest/services/"
ITEM_PAGE = "https://www.arcgis.com/home/item.html?id=0aa30dbf0e0949fa988adbfd3d9a15be"


class SurveyLayer(NamedTuple):
    name: str
    county: str
    url: str
    klass: str          # dilapidated | deteriorated | vacant_boarded


LAYERS: tuple[SurveyLayer, ...] = (
    SurveyLayer("edgecombe_dilapidated", "Edgecombe",
                _BASE + "Edgecombe_Dilapidated_Parcels_2025/FeatureServer/1", "dilapidated"),
    SurveyLayer("nash_dilapidated", "Nash",
                _BASE + "Nash_Dilapidated_Parcels_2025/FeatureServer/1", "dilapidated"),
    SurveyLayer("edgecombe_deteriorated", "Edgecombe",
                _BASE + "Edgecombe_Deteriorated_Parcels_2025/FeatureServer/1", "deteriorated"),
    SurveyLayer("nash_deteriorated", "Nash",
                _BASE + "Nash_Deteriorated_Parcels_2025/FeatureServer/1", "deteriorated"),
    SurveyLayer("edgecombe_vacant_boarded", "Edgecombe",
                _BASE + "edgecombe_vacant_boarded_2025_2/FeatureServer/0", "vacant_boarded"),
    SurveyLayer("nash_vacant_boarded", "Nash",
                _BASE + "nash_vacant_boarded_2025_2/FeatureServer/0", "vacant_boarded"),
)

#: Property-record columns only. Never "*".
FIELDS = (
    "PARNO", "ALTPARNO", "OWNNAME", "OWNNAME2",
    "MAILADD", "MCITY", "MSTATE", "MZIP",
    "SITEADD", "SCITY", "SZIP",
    "PARVAL", "IMPROVVAL", "LANDVAL", "STRUCTYEAR", "PARUSEDESC", "GISACRES",
)

#: Severity order when one parcel sits in several classes (strongest first).
_ORDER = ("dilapidated", "vacant_boarded", "deteriorated")


def _key(county: str, a: dict) -> Optional[tuple[str, str]]:
    pid = clean(a.get("PARNO")) or clean(a.get("ALTPARNO"))
    if pid:
        return county, "p:" + pid
    site = clean(a.get("SITEADD"))
    return (county, "a:" + site.lower()) if site else None


def fold(rows: Iterable[tuple[SurveyLayer, dict]]) -> dict[tuple[str, str], dict]:
    """Group rows by (county, parcel); keep the attributes and every class seen."""
    out: dict[tuple[str, str], dict] = {}
    for lay, a in rows:
        k = _key(lay.county, a)
        if not k:
            continue
        slot = out.setdefault(k, {"county": lay.county, "attrs": a, "classes": [], "layers": []})
        if lay.klass not in slot["classes"]:
            slot["classes"].append(lay.klass)
        slot["layers"].append(lay.name)
    for slot in out.values():
        slot["classes"].sort(key=_ORDER.index)
    return out


def to_listing(slot: dict, *, now: Optional[datetime] = None) -> Optional[Listing]:
    a = slot["attrs"]
    county = slot["county"]
    classes: list[str] = slot["classes"]
    pid = clean(a.get("PARNO")) or clean(a.get("ALTPARNO"))
    situs = clean(a.get("SITEADD"))
    if not (pid or situs):
        return None
    owners = [o for o in (clean(a.get("OWNNAME")), clean(a.get("OWNNAME2"))) if o]
    owner = " & ".join(owners) or None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    raw: dict[str, Any] = {
        "blight_survey": {
            "year": 2025,
            "classes": classes,
            "layers": slot["layers"],
            "project": "25002586A Rocky Mount",
        },
        "arcgis_distress": {"layer": "rocky_mount_blight_survey_2025",
                            **{k: v for k, v in a.items() if v not in (None, "")}},
    }
    if "dilapidated" in classes:
        raw["condemned"] = True
    if "deteriorated" in classes or "dilapidated" in classes:
        raw["distressed"] = True
    if "vacant_boarded" in classes:
        raw["vacancy"] = {"vacant": True, "boarded_up": True,
                          "source": "rocky_mount_blight_survey_2025", "observed_year": 2025}
    mail = owner_mailing(owner, (a.get("MAILADD"), a.get("MCITY"), a.get("MSTATE"), a.get("MZIP")),
                         a.get("MSTATE"), situs, pid, "NC", "rocky_mount_blight_survey_2025")
    if mail:
        raw["owner_mailing"] = mail
    sy = a.get("STRUCTYEAR")
    try:
        year_built = int(sy) if sy not in (None, "", 0) and int(sy) > 1700 else None
    except (TypeError, ValueError):
        year_built = None
    label = "/".join(c.replace("_", " ") for c in classes)
    return Listing(
        source=SOURCE,
        source_url=ITEM_PAGE,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county=county,
        street_address=situs,
        city=clean(a.get("SCITY")),
        zip_code=clean(a.get("SZIP")),
        parcel_id=pid,
        owner_name=owner, defendant=owner,
        tax_value=num(a.get("PARVAL")),
        acreage=num(a.get("GISACRES")),
        year_built=year_built,
        land_use=clean(a.get("PARUSEDESC")),
        foreclosure_process="blight_survey",
        description=f"Rocky Mount 2025 survey ({county} NC): {label} — "
                    f"{' | '.join(b for b in (owner, situs) if b)}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class RockyMountBlightSurvey(BaseScraper):
    slug = SLUG
    name = "Rocky Mount NC 2025 dilapidated / deteriorated / vacant-boarded parcels"
    category = "county_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        pairs: list[tuple[SurveyLayer, dict]] = []
        guard = LayerHarvest(self.slug, [lay.name for lay in LAYERS], attempts=2)
        async with client(timeout=45.0) as c:
            with guard:
                for lay in LAYERS:
                    rows = await guard.harvest(lay.name, self._one(c, lay))
                    pairs.extend((lay, a) for a in rows)
        out = [li for li in (to_listing(s) for s in fold(pairs).values()) if li]
        log.info("rocky_mount_blight.done", rows=len(pairs), leads=len(out))
        return out

    @staticmethod
    def _one(c, lay: SurveyLayer):
        async def _run() -> list[dict]:
            return await fetch_attrs(c, lay.url, FIELDS)
        return _run
