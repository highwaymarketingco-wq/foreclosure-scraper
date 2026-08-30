"""FREE Census ACS rent estimate enrichment — no API key required.

The board has only 5.4% rent estimate coverage. This enricher fills the gap
using the Census ACS 5-year data API which provides median rent by ZIP Code
Tabulation Area (ZCTA5). The API is completely free, no key needed (though
a key raises the rate limit from 50 to 500 requests/min).

For each listing with a ZIP code but no rent estimate, we look up the ACS
median rent for that ZCTA5 and store it as a directional estimate. We also
derive a $/sqft figure when we have living_sqft.

Endpoint: https://api.census.gov/data/2023/acs/acs5?get=B25064_001E&for=zip%20code%20tabulation%20area:ZIP

B25064_001E = Median gross rent (dollars) for renter-occupied housing units.
"""
from __future__ import annotations

import os
import json
import structlog
from typing import Optional
from urllib.parse import quote_plus

from .models import Listing

log = structlog.get_logger()

# ACS 5-year estimate endpoint (2023 is the latest published as of 2026).
_ACS_BASE = "https://api.census.gov/data/2023/acs/acs5"
_RENT_VAR = "B25064_001E"  # Median gross rent (dollars)

# In-memory cache — one API call per ZIP per run.
_zip_cache: dict[str, Optional[int]] = {}
def _fetch_rent_for_zip(zip5: str) -> Optional[int]:
    """Query ACS API for median gross rent by ZCTA5. Returns rent in dollars."""
    if zip5 in _zip_cache:
        return _zip_cache[zip5]
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        log.debug("census_rent.no_api_key", hint="Get free key at https://api.census.gov/data/key_signup.html")
        _zip_cache[zip5] = None
        return None
    import httpx
    try:
        url = (f"{_ACS_BASE}?get={_RENT_VAR}"
               f"&for=zip%20code%20tabulation%20area:{zip5}"
               f"&key={key}")
        with httpx.Client(timeout=15.0, follow_redirects=True) as c:
            r = c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (foreclosure-scraper)",
                "Accept": "application/json",
            })
        if r.status_code != 200 or not r.text.startswith("["):
            # Census returns 200 + HTML "Invalid Key" page for ZCTAs with no
            # ACS data — not a real error, just no data for that ZIP.
            # Try tract-level fallback before giving up.
            tract_rent = _fetch_tract_rent(zip5)
            if tract_rent:
                _zip_cache[zip5] = tract_rent
                return tract_rent
            _zip_cache[zip5] = None
            return None
        data = json.loads(r.text)
        rent = _parse_acs_response(data)
        _zip_cache[zip5] = rent
        return rent
    except Exception as exc:
        log.debug("census_rent.zip_fetch_error", zip=zip5, error=str(exc)[:120])
        _zip_cache[zip5] = None
        return None


def _fetch_tract_rent(zip5: str) -> Optional[int]:
    """Fallback: get median rent via Census Geocoder tract lookup.

    Falls back to tract-level when ZCTA-level returns no data. Requires
    API key (verified 2026-08-25).
    """
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        return None
    import httpx
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as c:
            geo_url = ("https://geocoding.geo.census.gov/geocoder/geographies/address"
                       f"?street=Main+St&zip={zip5}"
                       "&benchmark=Public_AR_Current&vintage=Current_Current"
                       "&layers=Census+Tracts")
            r = c.get(geo_url, headers={
                "User-Agent": "Mozilla/5.0 (foreclosure-scraper)",
                "Accept": "application/json",
            })
            if r.status_code != 200 or not r.text.startswith("{"):
                return None
            geo = json.loads(r.text)

        tracts = geo.get("result", {}).get("geoographies", {}).get("Census Tracts", [])
        if not tracts:
            return None
        tract = tracts[0]
        tract_num = tract.get("TRACT")
        county_fips = tract.get("COUNTY")
        state_fips = tract.get("STATE")

        if not all([tract_num, county_fips, state_fips]):
            return None

        acs_url = (f"https://api.census.gov/data/2023/acs/acs5"
                   f"?get=B25064_001E,NAME"
                   f"&for=tract:{tract_num}"
                   f"&in=state:{state_fips}+county:{county_fips}"
                   f"&key={key}")
        r2 = c.get(acs_url, headers={
            "User-Agent": "Mozilla/5.0 (foreclosure-scraper)",
            "Accept": "application/json",
        })
        if r2.status_code != 200 or not r2.text.startswith("["):
            return None
        data = json.loads(r2.text)

        rent = _parse_acs_response(data)
        if rent:
            _zip_cache[zip5] = rent
            log.info("census_rent.tract_fallback", zip=zip5, rent=rent)
        return rent
    except Exception as exc:
        log.debug("census_tract_rent.fetch_error", zip=zip5, error=str(exc)[:120])
        return None


def _parse_acs_response(data: list) -> Optional[int]:
    """Parse ACS JSON response: [['B25064_001E','zip code tabulation area','ZZZZZ'],['1234','55555']]"""
    if not data or len(data) < 2:
        return None
    header = data[0]
    row = data[1]
    if _RENT_VAR not in header:
        return None
    idx = header.index(_RENT_VAR)
    if idx >= len(row):
        return None
    val = row[idx]
    if val is None or val == "-" or val == "null":
        return None
    try:
        rent = int(float(val))
    except (ValueError, TypeError):
        return None
    # Sanity check — median rent should be $200-$8000 range
    if rent < 100 or rent > 15000:
        return None
    return rent


def enrich_census_rent(listings: list[Listing]) -> dict:
    """Add ACS median rent to listings missing rent estimates.

    Writes:
      raw['census_rent'] = {'median_gross_rent': int, 'zcta5': str, 'source': 'acs_2023_5yr'}
      raw['estimated_monthly_rent_acs'] = int  (if living_sqft allows $/sqft calc)

    Skips listings that already have estimated_monthly_rent or rent_median_ppsf.
    """
    n = len(listings)
    filled = 0
    skipped_has_rent = 0
    skipped_no_zip = 0
    api_errors = 0

    # Collect unique ZIPs to fetch (batch)
    zips_to_fetch: set[str] = set()
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        # Skip if already has rent data (including previous census_rent)
        if (raw.get("estimated_monthly_rent")
                or raw.get("estimated_monthly_rent_extra")
                or raw.get("rent_median_ppsf")
                or raw.get("rent_median_ppsf_extra")
                or raw.get("census_rent")):
            skipped_has_rent += 1
            continue
        if not li.zip_code or len(li.zip_code) < 5:
            skipped_no_zip += 1
            continue
        zip5 = li.zip_code[:5].strip()
        if zip5.isdigit() and len(zip5) == 5:
            zips_to_fetch.add(zip5)

    log.info("census_rent.start", unique_zips=len(zips_to_fetch),
             skipped_has_rent=skipped_has_rent, skipped_no_zip=skipped_no_zip)

    # Fetch all unique ZIPs (cached in-memory)
    for zip5 in zips_to_fetch:
        rent = _fetch_rent_for_zip(zip5)
        if rent is None:
            api_errors += 1

    log.info("census_rent.fetched", cached=len(_zip_cache),
             with_data=len([v for v in _zip_cache.values() if v is not None]),
             no_data=api_errors)

    # Apply to listings
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        # Skip if already has rent data from comps/zillow
        if (raw.get("estimated_monthly_rent")
                or raw.get("estimated_monthly_rent_extra")
                or raw.get("rent_median_ppsf")
                or raw.get("rent_median_ppsf_extra")):
            continue
        if not li.zip_code or len(li.zip_code) < 5:
            continue
        zip5 = li.zip_code[:5].strip()
        if not zip5.isdigit():
            continue
        rent = _zip_cache.get(zip5)
        if rent is None:
            continue

        raw["census_rent"] = {
            "median_gross_rent": rent,
            "zcta5": zip5,
            "source": "acs_2023_5yr",
        }
        # If we have living_sqft, derive $/sqft estimate
        if li.living_sqft and li.living_sqft > 200:
            # Use median rent directly as the monthly estimate for the area
            raw["estimated_monthly_rent_acs"] = rent
        else:
            # For land or unknown sqft, still store the area median
            raw["estimated_monthly_rent_acs"] = rent
        li.raw = raw
        filled += 1

    log.info("census_rent.done", filled=filled, total=n,
             skipped_has_rent=skipped_has_rent, skipped_no_zip=skipped_no_zip,
             api_errors=api_errors)
    return {
        "filled": filled,
        "unique_zips": len(zips_to_fetch),
        "cached_rents": len([v for v in _zip_cache.values() if v is not None]),
        "api_errors": api_errors,
    }
