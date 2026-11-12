"""FREE Census ACS tract/ZCTA demographic enrichment — no scraping, one key.

docs/rei_operator_playbook.md Tier 1 #2 flagged this as missing: "free per-
tract buy-box + motivation scoring layer... income, owner-occupancy, vacancy,
value, age of housing per tract; we don't have a demographic scoring layer
today." enrichment_census_rent.py already proved out the ACS API + free key
+ ZCTA5 pattern for ONE variable (median rent); this pulls five more in the
SAME single request (the ACS API accepts a comma-separated `get=` list, so
adding variables costs nothing extra in requests or rate-limit budget) and
writes a distinct, more complete signal:

  - B19013_001E  median household income
  - B25077_001E  median home value (owner-occupied)
  - B25003_001E / B25003_002E  occupied units / owner-occupied -> owner-occ %
  - B25002_001E / B25002_003E  total units / vacant -> vacancy %
  - B25035_001E  median year structure built

Live-verified 2026-09-17 against ZCTA5 28801 (Asheville, NC): income $51,125,
home value $481,400, owner-occ 36.7%, vacancy 28.4%, median year 1963 -- all
plausible for a downtown/tourist ZIP. Endpoint, key, and rate-limit behavior
are identical to enrichment_census_rent.py (500 req/min with a key); this
module keeps its own cache so it never re-fetches a ZIP census_rent already
pulled, but the two are independent API calls (different variable sets),
not shared cache entries.
"""
from __future__ import annotations

import os
import json
import structlog
from typing import Optional
from urllib.parse import quote_plus

from .models import Listing

log = structlog.get_logger()

_ACS_BASE = "https://api.census.gov/data/2023/acs/acs5"
_VARS = (
    "B19013_001E",  # median household income
    "B25077_001E",  # median home value
    "B25003_001E",  # occupied housing units (tenure universe)
    "B25003_002E",  # owner-occupied units
    "B25002_001E",  # total housing units (occupancy universe)
    "B25002_003E",  # vacant units
    "B25035_001E",  # median year structure built
)

# In-memory cache — one API call per ZIP per run.
_zip_cache: dict[str, Optional[dict]] = {}


def _sane(val, lo, hi) -> Optional[float]:
    if val is None or val in ("-", "null", ""):
        return None
    try:
        n = float(val)
    except (ValueError, TypeError):
        return None
    if n < lo or n > hi:
        return None
    return n


def _parse_acs_row(header: list, row: list) -> Optional[dict]:
    idx = {v: header.index(v) for v in _VARS if v in header}
    if len(idx) < len(_VARS):
        return None

    def get(var):
        i = idx[var]
        return row[i] if i < len(row) else None

    income = _sane(get("B19013_001E"), 1_000, 500_000)
    home_value = _sane(get("B25077_001E"), 5_000, 10_000_000)
    occ_total = _sane(get("B25003_001E"), 1, 1_000_000)
    owner_occ = _sane(get("B25003_002E"), 0, 1_000_000)
    units_total = _sane(get("B25002_001E"), 1, 1_000_000)
    vacant = _sane(get("B25002_003E"), 0, 1_000_000)
    year_built = _sane(get("B25035_001E"), 1800, 2027)

    out: dict = {}
    if income is not None:
        out["median_household_income"] = int(income)
    if home_value is not None:
        out["median_home_value"] = int(home_value)
    if occ_total and owner_occ is not None and owner_occ <= occ_total:
        out["owner_occupied_pct"] = round(owner_occ / occ_total * 100, 1)
    if units_total and vacant is not None and vacant <= units_total:
        out["vacant_housing_pct"] = round(vacant / units_total * 100, 1)
    if year_built is not None:
        out["median_year_built"] = int(year_built)

    return out or None


def _fetch_demographics_for_zip(zip5: str) -> Optional[dict]:
    if zip5 in _zip_cache:
        return _zip_cache[zip5]
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        log.debug("census_demographics.no_api_key",
                   hint="Get free key at https://api.census.gov/data/key_signup.html")
        _zip_cache[zip5] = None
        return None
    import httpx
    try:
        url = (f"{_ACS_BASE}?get={quote_plus(','.join(_VARS))}"
               f"&for=zip%20code%20tabulation%20area:{zip5}"
               f"&key={key}")
        with httpx.Client(timeout=15.0, follow_redirects=True) as c:
            r = c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (foreclosure-scraper)",
                "Accept": "application/json",
            })
        if r.status_code != 200 or not r.text.startswith("["):
            _zip_cache[zip5] = None
            return None
        data = json.loads(r.text)
        if not data or len(data) < 2:
            _zip_cache[zip5] = None
            return None
        parsed = _parse_acs_row(data[0], data[1])
        _zip_cache[zip5] = parsed
        return parsed
    except Exception as exc:
        log.debug("census_demographics.zip_fetch_error", zip=zip5, error=str(exc)[:120])
        _zip_cache[zip5] = None
        return None


def enrich_census_demographics(listings: list[Listing]) -> dict:
    """Add ACS ZCTA-level demographics (income/home value/owner-occ/vacancy/
    year built) to listings missing them.

    Writes raw['census_demographics'] = {median_household_income,
    median_home_value, owner_occupied_pct, vacant_housing_pct,
    median_year_built, zcta5, source}.

    Idempotent: skips listings that already have raw['census_demographics'].
    """
    n = len(listings)
    filled = 0
    skipped_has_data = 0
    skipped_no_zip = 0
    api_errors = 0

    zips_to_fetch: set[str] = set()
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("census_demographics"):
            skipped_has_data += 1
            continue
        if not li.zip_code or len(li.zip_code) < 5:
            skipped_no_zip += 1
            continue
        zip5 = li.zip_code[:5].strip()
        if zip5.isdigit() and len(zip5) == 5:
            zips_to_fetch.add(zip5)

    log.info("census_demographics.start", unique_zips=len(zips_to_fetch),
             skipped_has_data=skipped_has_data, skipped_no_zip=skipped_no_zip)

    for zip5 in zips_to_fetch:
        if _fetch_demographics_for_zip(zip5) is None:
            api_errors += 1

    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("census_demographics"):
            continue
        if not li.zip_code or len(li.zip_code) < 5:
            continue
        zip5 = li.zip_code[:5].strip()
        if not zip5.isdigit():
            continue
        demo = _zip_cache.get(zip5)
        if not demo:
            continue
        raw["census_demographics"] = {**demo, "zcta5": zip5, "source": "acs_2023_5yr"}
        li.raw = raw
        filled += 1

    log.info("census_demographics.done", filled=filled, total=n,
             skipped_has_data=skipped_has_data, skipped_no_zip=skipped_no_zip,
             api_errors=api_errors)
    return {
        "filled": filled,
        "unique_zips": len(zips_to_fetch),
        "api_errors": api_errors,
    }
