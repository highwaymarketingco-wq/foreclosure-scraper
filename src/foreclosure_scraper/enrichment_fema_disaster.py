"""FEMA disaster-declaration + Individual Assistance registration enrichment.

Queries FEMA's free OpenFEMA API for Hurricane Helene disaster declarations
(DR-4827 NC, DR-4829 SC — note: the task brief said 4828 for SC, but DR-4828 is
actually the *Florida* Helene declaration; SC's is DR-4829) and for IA
registration counts by county. Properties in disaster-declared counties that
also have high IA registration volume are high-motivation leads — the IA data
is a direct proxy for "how many households in this county registered for
federal disaster assistance," which tracks property damage density.

Two OpenFEMA endpoints, both free, no auth, no key:

  * DisasterDeclarationsSummaries (v2)
    https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
    One row per (disaster, county) — so DR-4827 returns ~40 rows (NC counties +
    tribal area). Each row carries declaration type/date, incident dates, and
    the four assistance-program flags (IH, IA, PA, HM). We fetch ALL rows for a
    disaster in a single request ($top=100 is enough) and collapse to one
    disaster summary + a county list.

  * IndividualsAndHouseholdsProgramValidRegistrations (v2)
    https://www.fema.gov/api/open/v2/IndividualsAndHouseholdsProgramValidRegistrations
    One row per IA *applicant*. DR-4827 has ~283K rows, DR-4829 ~444K — far too
    many to fetch in full on every run. The API does NOT support $apply
    (server-side aggregation), so we page with $select (county + state only,
    minimal payload) and aggregate client-side into a county→count dict. With
    $top=50000 and $select, each page is ~0.5–6s; a full county rollup for both
    disasters is ~15 pages / ~60s. Results are cached to disk (JSON) with a TTL
    so normal runs do no heavy pagination.

Stamps ``raw['fema_disaster']`` on each listing whose county is in a declared
disaster area, with declaration metadata + that county's IA registration count
(if available). Also stamps ``raw['fema_disaster']['ia_rank_pct']`` — the
county's registration count as a percentile within the disaster, so "Buncombe
(top 5% of IA registrations)" is a directly usable lead-priority signal.

Self-contained: uses httpx directly (not the shared http_client, since FEMA's
API has different rate-limit characteristics and we need concurrent paging).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

# --- endpoints --------------------------------------------------------------
_DD_API = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
_IA_API = (
    "https://www.fema.gov/api/open/v2/"
    "IndividualsAndHouseholdsProgramValidRegistrations"
)

# Hurricane Helene disaster declarations.
# DR-4827 = NC (Tropical Storm Helene), declared 2024-09-28
# DR-4829 = SC (Hurricane Helene), declared 2024-09-29
# (DR-4828 = FL Hurricane Helene — not relevant to our NC/SC footprint)
HELENE_DISASTERS: dict[str, int] = {
    "NC": 4827,
    "SC": 4829,
}

# IA pagination: $top capped at 50k by the API (50k works, 100k times out).
_IA_PAGE_SIZE = 50_000
# Safety cap on total pages per disaster (50k * 20 = 1M records ceiling).
_MAX_IA_PAGES = 20

# Disk cache for the IA county rollup (the expensive part).
_CACHE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "fema_disaster"
)
# IA registration data refreshes weekly on FEMA's side; 6h TTL is plenty.
_CACHE_TTL_S = 6 * 3600

# HTTP settings — FEMA's API is generally fast but intermittently 503s.
_TIMEOUT = 60.0
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 2.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _county_name_from_designated_area(area: str) -> str:
    """'Alexander (County)' -> 'Alexander'. Pass through non-county areas."""
    m = re.match(r"^(.+?)\s*\(County\)\s*$", area or "")
    return m.group(1).strip() if m else (area or "").strip()


def _normalize_county(name: str | None) -> str:
    """'Buncombe County' / 'buncombe' / 'BUNCOMBE (County)' -> 'Buncombe'."""
    if not name:
        return ""
    s = name.strip()
    # Strip trailing ' County' / ' Parish' / ' (County)'
    s = re.sub(r"\s*\(County\)\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+County\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+Parish\s*$", "", s, flags=re.IGNORECASE)
    return s.strip().title()


async def _fema_get(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
) -> dict[str, Any] | None:
    """GET with retry on 503/timeout. Returns parsed JSON or None on failure."""
    for attempt in range(_MAX_RETRIES):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (502, 503, 429):
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                log.debug(
                    "fema.retry",
                    status=r.status_code,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)
                continue
            # Non-retryable HTTP error
            log.warning(
                "fema.http_error",
                status=r.status_code,
                body=r.text[:300],
            )
            return None
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            log.debug("fema.conn_retry", attempt=attempt + 1, delay=delay,
                      error=str(exc)[:120])
            await asyncio.sleep(delay)
    log.warning("fema.exhausted_retries", url=url)
    return None


# ---------------------------------------------------------------------------
# Disaster Declarations Summaries
# ---------------------------------------------------------------------------

async def fetch_disaster_declaration(
    client: httpx.AsyncClient,
    disaster_number: int,
) -> dict[str, Any] | None:
    """Fetch all county rows for one disaster number and collapse into a
    single summary dict.

    Returns:
        {
            disaster_number, fema_declaration_string, state, declaration_type,
            declaration_date, incident_begin_date, incident_end_date,
            incident_type, declaration_title,
            programs: {ih, ia, pa, hm},  # booleans
            last_ia_filing_date,
            counties: [list of county names],
            designated_areas: [raw designatedArea strings],
            raw_count: int,
        }
    or None on API failure.
    """
    params = {
        "$filter": f"disasterNumber eq {disaster_number}",
        "$top": "200",  # plenty for any single disaster
        "$metadata": "off",
    }
    data = await _fema_get(client, _DD_API, params)
    if not data:
        return None

    records = data.get("DisasterDeclarationsSummaries", [])
    if not records:
        log.warning("fema.dd_empty", disaster_number=disaster_number)
        return None

    # All rows for a disaster share the same disaster-level fields; first row
    # is authoritative. County-level info varies per row (designatedArea).
    r0 = records[0]
    counties: list[str] = []
    designated_areas: list[str] = []
    for rec in records:
        area = rec.get("designatedArea") or ""
        designated_areas.append(area)
        county = _county_name_from_designated_area(area)
        if county and county not in counties:
            counties.append(county)

    return {
        "disaster_number": disaster_number,
        "fema_declaration_string": r0.get("femaDeclarationString"),
        "state": r0.get("state"),
        "declaration_type": r0.get("declarationType"),
        "declaration_date": (r0.get("declarationDate") or "")[:10],
        "incident_begin_date": (r0.get("incidentBeginDate") or "")[:10],
        "incident_end_date": (r0.get("incidentEndDate") or "")[:10],
        "incident_type": r0.get("incidentType"),
        "declaration_title": r0.get("declarationTitle"),
        "programs": {
            "ih": bool(r0.get("ihProgramDeclared")),
            "ia": bool(r0.get("iaProgramDeclared")),
            "pa": bool(r0.get("paProgramDeclared")),
            "hm": bool(r0.get("hmProgramDeclared")),
        },
        "last_ia_filing_date": (r0.get("lastIAFilingDate") or "")[:10] or None,
        "counties": counties,
        "designated_areas": designated_areas,
        "raw_count": len(records),
    }


# ---------------------------------------------------------------------------
# Individual Assistance — county-level registration counts
# ---------------------------------------------------------------------------

def _cache_path(disaster_number: int) -> Path:
    return _CACHE_DIR / f"ia_county_{disaster_number}.json"


def _read_cache(disaster_number: int) -> dict[str, Any] | None:
    p = _cache_path(disaster_number)
    if not p.exists():
        return None
    try:
        cached = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    fetched_at = cached.get("fetched_at", 0)
    if isinstance(fetched_at, (int, float)):
        age = time.time() - fetched_at
        if age < _CACHE_TTL_S:
            return cached
    return None


def _write_cache(disaster_number: int, payload: dict[str, Any]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(disaster_number).write_text(
            json.dumps(payload, indent=2, sort_keys=True)
        )
    except OSError as exc:
        log.warning("fema.cache_write_failed", error=str(exc)[:120])


async def fetch_ia_county_counts(
    client: httpx.AsyncClient,
    disaster_number: int,
) -> dict[str, int] | None:
    """Page through IA registrations for one disaster, aggregating by county.

    Returns ``{"County Name": registration_count, ...}`` or None on failure.

    With ~283K–444K registrations per disaster and $top=50000, this is 6–9
    pages per disaster. Each page carries only county + state ($select), so
    payloads are small. Results cached to disk for 6 hours.
    """
    # --- cache ---
    cached = _read_cache(disaster_number)
    if cached:
        counts_dict = cached.get("counties", {})
        log.info("fema.ia_cache_hit", disaster=disaster_number,
                 counties=len(counts_dict))
        return counts_dict if counts_dict else None

    counts: Counter[str] = Counter()
    total_fetched = 0
    skip = 0

    for page in range(_MAX_IA_PAGES):
        params = {
            "$filter": f"disasterNumber eq {disaster_number}",
            "$top": str(_IA_PAGE_SIZE),
            "$skip": str(skip),
            "$select": "county,damagedStateAbbreviation",
            "$metadata": "off",
        }
        data = await _fema_get(client, _IA_API, params)
        if not data:
            log.warning("fema.ia_page_failed", disaster=disaster_number,
                        page=page, skip=skip)
            break

        records = data.get(
            "IndividualsAndHouseholdsProgramValidRegistrations", []
        )
        if not records:
            break

        for rec in records:
            county_raw = rec.get("county") or ""
            county = _normalize_county(county_raw)
            if county:
                counts[county] += 1

        total_fetched += len(records)
        log.info("fema.ia_page", disaster=disaster_number, page=page,
                 records=len(records), total=total_fetched,
                 counties_so_far=len(counts))

        if len(records) < _IA_PAGE_SIZE:
            break  # last page
        skip += _IA_PAGE_SIZE

    if not counts:
        return None

    # Persist to cache
    _write_cache(disaster_number, {
        "disaster_number": disaster_number,
        "fetched_at": time.time(),
        "total_registrations": total_fetched,
        "counties": dict(counts),
    })

    log.info("fema.ia_done", disaster=disaster_number,
             total_registrations=total_fetched, counties=len(counts))
    return dict(counts)


def _percentile_rank(value: float, all_values: list[float]) -> float:
    """Percentile rank of `value` within `all_values` (0–100)."""
    if not all_values:
        return 0.0
    below = sum(1 for v in all_values if v < value)
    equal = sum(1 for v in all_values if v == value)
    # Standard percentile rank formula
    return round(100.0 * (below + 0.5 * equal) / len(all_values), 1)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

async def fetch_helene_disaster_data() -> dict[str, Any]:
    """Fetch Hurricane Helene disaster declarations + IA county counts for
    both NC (DR-4827) and SC (DR-4829).

    Returns a dict keyed by state:

        {
          "NC": {
            "declaration": { ...disaster summary... },
            "ia_counts": { "Buncombe": 23456, ... } | None,
          },
          "SC": { ... },
        }

    This is the main entry point for batch enrichment and for CLI/standalone
    use. All network I/O is concurrent and retried.
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": "foreclosure-scraper/1.0 (openfema client)",
    }
    results: dict[str, Any] = {}

    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers=headers, follow_redirects=True
    ) as client:
        # Fetch both disaster declarations concurrently
        dd_tasks = {
            state: fetch_disaster_declaration(client, dn)
            for state, dn in HELENE_DISASTERS.items()
        }
        dd_results = await asyncio.gather(*dd_tasks.values())

        # Fetch IA counts concurrently (each does its own pagination)
        ia_tasks = {
            state: fetch_ia_county_counts(client, dn)
            for state, dn in HELENE_DISASTERS.items()
        }
        ia_results = await asyncio.gather(*ia_tasks.values())

        for (state, _), dd_data, ia_data in zip(
            dd_tasks.items(), dd_results, ia_results
        ):
            results[state] = {
                "declaration": dd_data,
                "ia_counts": ia_data,
            }

    return results


async def enrich_with_fema_disaster(listings: list[Listing]) -> dict[str, Any]:
    """Stamp ``raw['fema_disaster']`` on listings in declared disaster counties.

    For each listing, if its (state, county) matches a Hurricane Helene
    declared county, attaches:

        raw['fema_disaster'] = {
            "disaster_number": 4827,
            "fema_declaration_string": "DR-4827-NC",
            "declaration_type": "DR",
            "declaration_date": "2024-09-28",
            "incident_type": "Tropical Storm",
            "declaration_title": "TROPICAL STORM HELENE",
            "programs": {"ih": true, "ia": false, "pa": true, "hm": true},
            "last_ia_filing_date": "2025-04-07",
            "county": "Buncombe",
            "ia_registrations": 23456,          # int or None
            "ia_rank_pct": 98.5,                # percentile within disaster
            "total_ia_counties": 39,
        }

    Returns a stats dict for the run report.
    """
    if not listings:
        return {"matched": 0, "with_ia": 0, "total": 0}

    # Fetch all disaster data once
    disaster_data = await fetch_helene_disaster_data()

    # Build lookup: (state, normalized_county) -> (declaration, ia_count, ia_rank)
    county_index: dict[tuple[str, str], dict[str, Any]] = {}

    for state, data in disaster_data.items():
        declaration = data.get("declaration")
        ia_counts: dict[str, int] | None = data.get("ia_counts")

        if not declaration:
            continue

        counties = declaration.get("counties", [])
        # Precompute percentile ranks for this disaster's counties
        all_ia_values: list[float] = []
        if ia_counts:
            all_ia_values = [
                float(ia_counts.get(c, 0)) for c in counties
            ]

        for county_name in counties:
            norm = _normalize_county(county_name)
            if not norm:
                continue
            ia_count = ia_counts.get(norm) if ia_counts else None
            rank_pct = None
            if ia_counts and ia_count is not None and all_ia_values:
                rank_pct = _percentile_rank(float(ia_count), all_ia_values)

            county_index[(state.upper(), norm)] = {
                "disaster_number": declaration["disaster_number"],
                "fema_declaration_string": declaration.get(
                    "fema_declaration_string"
                ),
                "declaration_type": declaration.get("declaration_type"),
                "declaration_date": declaration.get("declaration_date"),
                "incident_begin_date": declaration.get("incident_begin_date"),
                "incident_end_date": declaration.get("incident_end_date"),
                "incident_type": declaration.get("incident_type"),
                "declaration_title": declaration.get("declaration_title"),
                "programs": declaration.get("programs"),
                "last_ia_filing_date": declaration.get("last_ia_filing_date"),
                "county": norm,
                "ia_registrations": ia_count,
                "ia_rank_pct": rank_pct,
                "total_ia_counties": len(ia_counts) if ia_counts else None,
            }

    if not county_index:
        log.warning("fema_disaster.no_county_index")
        return {"matched": 0, "with_ia": 0, "total": len(listings)}

    # Match listings
    matched = 0
    with_ia = 0
    for li in listings:
        state = (li.state or "").strip().upper()
        county = _normalize_county(li.county)
        if not state or not county:
            continue

        info = county_index.get((state, county))
        if not info:
            continue

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["fema_disaster"] = dict(info)
        matched += 1
        if info.get("ia_registrations") is not None:
            with_ia += 1

    log.info(
        "fema_disaster.done",
        matched=matched,
        with_ia=with_ia,
        total=len(listings),
        counties_indexed=len(county_index),
    )
    return {
        "matched": matched,
        "with_ia": with_ia,
        "total": len(listings),
        "counties_indexed": len(county_index),
    }


# ---------------------------------------------------------------------------
# CLI / standalone
# ---------------------------------------------------------------------------

async def _print_report() -> None:
    """Standalone CLI: fetch and print Hurricane Helene disaster data."""
    print("Fetching FEMA Hurricane Helene disaster data...\n")
    data = await fetch_helene_disaster_data()

    for state in ("NC", "SC"):
        sd = data.get(state, {})
        declaration = sd.get("declaration")
        ia_counts = sd.get("ia_counts")

        print(f"{'=' * 70}")
        if not declaration:
            print(f"{state}: FAILED to fetch declaration")
            continue

        print(f"{state} — {declaration['fema_declaration_string']}")
        print(f"  Title:          {declaration['declaration_title']}")
        print(f"  Type:           {declaration['declaration_type']} "
              f"({declaration['incident_type']})")
        print(f"  Declared:       {declaration['declaration_date']}")
        print(f"  Incident dates: {declaration['incident_begin_date']} "
              f"→ {declaration['incident_end_date']}")
        print(f"  Last IA filing: {declaration.get('last_ia_filing_date')}")
        progs = declaration.get("programs", {})
        prog_str = ", ".join(
            k.upper() for k, v in progs.items() if v
        ) or "none"
        print(f"  Programs:       {prog_str}")
        print(f"  Counties ({len(declaration['counties'])}):")

        if ia_counts:
            # Sort counties by IA registration count descending
            sorted_counties = sorted(
                declaration["counties"],
                key=lambda c: ia_counts.get(c, 0),
                reverse=True,
            )
            all_vals = [float(ia_counts.get(c, 0))
                        for c in declaration["counties"]]
            for county in sorted_counties:
                count = ia_counts.get(county, 0)
                pct = _percentile_rank(float(count), all_vals)
                print(f"    {county:25s}  {count:>8,} reg  "
                      f"(pct: {pct:>5.1f})")
            print(f"  Total IA registrations: "
                  f"{sum(ia_counts.values()):,}")
        else:
            for county in declaration["counties"]:
                print(f"    {county}")
            print("  (IA registration data unavailable)")
        print()

    print(f"{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(_print_report())
