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

MEASURED STATEWIDE (widened 2026-10-03, was MEASURED IN-FOOTPRINT)
    Live-checked 2026-10-03: ACRES NC 1,145 rows / 75 distinct counties, SEMS
    NC 1,333 rows / 97 counties, ACRES SC 561 rows / 43 counties, SEMS SC 770
    rows / 47 counties. The query below (one GET per state per program)
    already pulls every one of those rows -- FOOTPRINT used to keep only the
    rows from the 18-county (11 NC + 7 SC) flip footprint and silently drop
    the rest, at zero fetch-cost savings since the fetch is state-wide either
    way. The 2026-09-15 in_scope_distressed mandate ("if its a distressed
    property its anywhere in nc and sc") makes every one of those discarded
    rows admissible for this generic DISTRESSED-type lead, so FOOTPRINT now
    maps every real NC/SC county (validation.py), not just the flip
    footprint. Same bug class 2026-10-03's comps fix closed for
    enrichment_comps.py: an enricher/scraper scoped to the old 18-county
    footprint that was never revisited when the lead population expanded.

    Counties are still matched client-side (not trusted directly) because FRS
    has no county parameter and its county_name is a plain uppercase string
    that occasionally carries a data-entry typo (e.g. "BURTCOMBE",
    "ALLLENDALE" -- both verified live 2026-10-03) which this dict will not
    match; those few rows still drop, same as before, just no longer the
    large majority of the source.
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
from ...validation import NC_COUNTIES as _NC_COUNTY_NAMES, SC_COUNTIES as _SC_COUNTY_NAMES

log = structlog.get_logger()

FRS = "https://data.epa.gov/dmapservice/frs.frs_program_facility"

#: Canonical spellings, keyed by the uppercase form FRS actually returns.
#: Every real NC/SC county (validation.py) -- see module docstring.
FOOTPRINT = {
    "NC": {c.upper(): c for c in _NC_COUNTY_NAMES},
    "SC": {c.upper(): c for c in _SC_COUNTY_NAMES},
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
    # registry_id is FRS's own cross-program facility key. It resolves to a
    # real, free, public per-facility detail page (verified live 2026-10-01:
    # https://ofmpub.epa.gov/frs_public2/fii_query_dtl.disp_program_facility
    # ?p_registry_id=<id>, HTTP 200, no auth) carrying fields this list
    # endpoint doesn't return at all: SIC/NAICS codes, alternative names,
    # responsible-party organizations, and -- for SEMS rows -- NPL vs
    # non-NPL status. Every row used to ship the same generic
    # "https://www.epa.gov/frs" source_url regardless of which facility it
    # was, so there was no way to click through to the specific site.
    registry_id = _clean(row.get("registry_id"))
    detail_url = (
        f"https://ofmpub.epa.gov/frs_public2/fii_query_dtl.disp_program_facility"
        f"?p_registry_id={registry_id}"
        if registry_id else "https://www.epa.gov/frs"
    )
    return Listing(
        source=f"counties_generic.epa_frs.{program.lower()}",
        source_url=detail_url,
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
            "registry_id": registry_id,
            "site_name": name,
            "county_name": _clean(row.get("county_name")),
            "location_description": _clean(row.get("location_description")),
            "last_reported_date": _clean(row.get("last_reported_date")),
            # EXTRACTION-COMPLETENESS AUDIT 2026-10-03: live field-population
            # survey across all 3,809 current NC+SC ACRES/SEMS rows found
            # every other unused FRS column null on 100% of rows except this
            # one (0.4%, 14 rows) -- and where it IS populated it carries
            # real content this list endpoint has no other field for: an
            # alternate/former street address, additional parcel numbers the
            # same site covers, or a literal PIN ("PIN 4599156896"). Already
            # fetched in the same response; costs nothing to keep.
            "supplemental_location": _clean(row.get("supplemental_location")),
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
