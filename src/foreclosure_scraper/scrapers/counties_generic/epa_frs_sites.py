"""EPA brownfield and Superfund sites, via the Facility Registry Service.

WHY THESE ARE DISTRESS
    A brownfield or Superfund listing is a recorded environmental encumbrance on
    a specific parcel. It suppresses value, complicates financing, and is
    frequently the reason a commercial or industrial property has sat unsold for
    years. It also crosses both states in one query, which is what the counties
    with thin local data need.

WHY THROUGH FRS RATHER THAN THE PROGRAM ENDPOINTS
    The direct SEMS endpoint (sems.envirofacts_site) returns HTTP 500 — checked
    2026-08-06 for both NC and SC. The Facility Registry Service carries the same
    programs keyed by pgm_sys_acrnm and answers 200, so both ACRES (brownfields)
    and SEMS (Superfund) are read through it.

MEASURED IN-FOOTPRINT, not estimated
    ACRES  1,698 statewide -> 161 in footprint
    SEMS     795 statewide -> 110 in footprint

    Counties are filtered client-side because FRS has no county parameter, and
    its county_name is a plain uppercase string that has to be matched against
    the footprint rather than trusted.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

FRS = "https://data.epa.gov/dmapservice/frs.frs_program_facility"

#: Canonical spellings, keyed by the uppercase form FRS actually returns.
FOOTPRINT = {
    "NC": {"BUNCOMBE": "Buncombe", "HENDERSON": "Henderson",
           "RUTHERFORD": "Rutherford", "POLK": "Polk",
           "TRANSYLVANIA": "Transylvania", "MCDOWELL": "McDowell",
           "CLEVELAND": "Cleveland", "GASTON": "Gaston", "LINCOLN": "Lincoln",
           "BURKE": "Burke", "MITCHELL": "Mitchell"},
    "SC": {"SPARTANBURG": "Spartanburg", "CHEROKEE": "Cherokee",
           "ANDERSON": "Anderson", "PICKENS": "Pickens", "OCONEE": "Oconee",
           "LAURENS": "Laurens", "UNION": "Union"},
}

#: pgm_sys_acrnm -> (human label, process tag)
PROGRAMS = {
    "ACRES": ("EPA brownfield", "brownfield"),
    "SEMS": ("EPA Superfund / CERCLIS", "superfund"),
}


def _clean(v) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    if not s or s.upper() in ("NA", "N/A", "NONE", "NULL", "UNKNOWN"):
        return None
    return s


def _to_listing(row: dict, state: str, program: str) -> Optional[Listing]:
    county = FOOTPRINT[state].get((row.get("county_name") or "").upper().strip())
    if not county:
        return None                       # outside the footprint
    addr = _clean(row.get("location_address"))
    if not addr:
        return None                       # no address, no lead
    label, process = PROGRAMS[program]
    name = _clean(row.get("primary_name")) or _clean(row.get("pgm_sys_id"))
    now = datetime.utcnow()
    return Listing(
        source=f"counties_generic.epa_frs.{program.lower()}",
        source_url="https://www.epa.gov/frs",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state=state, county=county,
        street_address=addr,
        city=_clean(row.get("city_name")),
        zip_code=_clean(row.get("postal_code")),
        owner_name=name, defendant=name,
        case_number=_clean(row.get("pgm_sys_id")),
        foreclosure_process=process,
        description=f"{county} {state} — {label} — "
                    f"{' | '.join(x for x in (name, addr) if x)}"[:300],
        first_seen=now, last_seen=now,
        raw={"epa_frs": {
            "program": program,
            "pgm_sys_id": _clean(row.get("pgm_sys_id")),
            "site_name": name,
            "county_name": _clean(row.get("county_name")),
            "location_description": _clean(row.get("location_description")),
            "last_reported_date": _clean(row.get("last_reported_date")),
        }},
    )


async def _fetch(c, program: str) -> list[Listing]:
    out: list[Listing] = []
    for state in ("NC", "SC"):
        url = (f"{FRS}/pgm_sys_acrnm/equals/{program}"
               f"/and/state_code/equals/{state}/1:20000/JSON")
        r = await c.get(url, timeout=120.0)
        if r.status_code != 200:
            raise RuntimeError(f"{program}/{state}: HTTP {r.status_code}")
        try:
            rows = r.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{program}/{state}: response is not JSON") from exc
        kept = 0
        for row in rows or []:
            li = _to_listing(row, state, program)
            if li:
                out.append(li)
                kept += 1
        log.info("epa_frs.state_done", program=program, state=state,
                 statewide=len(rows or []), in_footprint=kept)
    return out


class EpaFrsSites(BaseScraper):
    slug = "counties_generic.epa_frs_sites"
    name = "EPA brownfield (ACRES) + Superfund (SEMS) sites via FRS"
    category = "state_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_EPA_FRS") == "0":
            return []
        out: list[Listing] = []
        guard = LayerHarvest(self.slug, list(PROGRAMS), attempts=3)
        async with client(timeout=120.0) as c:
            with guard:
                for program in PROGRAMS:
                    out.extend(await guard.harvest(program, self._one(c, program)))
        return out

    @staticmethod
    def _one(c, program: str):
        async def _run() -> list[Listing]:
            return await _fetch(c, program)
        return _run
