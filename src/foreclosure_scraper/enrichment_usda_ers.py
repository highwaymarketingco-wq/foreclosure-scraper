"""USDA Economic Research Service enrichment — county economic indicators.

The USDA Economic Research Service (ERS) provides county-level economic data
via both a public API and downloadable CSVs. The API key is optional —
without it, requests work at a lower rate limit.

We query/collect:
  1. Rural-urban continuum code (RUCC) — urbanicity classification 1-9
  2. Poverty rate — percentage of population below poverty line
  3. Unemployment rate — county unemployment rate

Data sources:
  - API: https://api.ers.usda.gov (key from USDA_API_KEY in .env, optional)
  - CSV fallback: ERS county-level data files (no key needed)

This enricher fills: raw["economic"] dict with county-level economic data.
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

USDA_API_BASE = "https://api.ers.usda.gov"

# ERS county-level CSV downloads (free, no key needed)
# Rural-urban continuum codes — updated periodically by ERS
RUCC_CSV_URL = (
    "https://www.ers.usda.gov/webdocs/DataFiles/53218/"
    "Ruralurbancontinuumcodes2023.csv"
)
# County unemployment & median household income (ERS / Bureau of Labor)
UNEMP_CSV_URL = (
    "https://www.ers.usda.gov/webdocs/DataFiles/53218/"
    "Unemployment.csv"
)
# County poverty rates (ERS / Census SAIPE)
POVERTY_CSV_URL = (
    "https://www.ers.usda.gov/webdocs/DataFiles/53218/"
    "Poverty.csv"
)

_SEMAPHORE = asyncio.Semaphore(3)

# In-memory caches: {fips_code: {fields}}
_RUCC_CACHE: dict[str, dict[str, Any]] | None = None
_UNEMP_CACHE: dict[str, dict[str, Any]] | None = None
_POVERTY_CACHE: dict[str, dict[str, Any]] | None = None
_CSVS_LOADED = False


def _get_api_key() -> str | None:
    """Read the USDA API key from the environment (optional)."""
    key = os.environ.get("USDA_API_KEY", "").strip()
    return key if key else None


async def _download_csv(url: str) -> str | None:
    """Download a CSV via the shared HTTP client. Returns text or None."""
    try:
        async with client(timeout=30.0) as c:
            resp = await c.get(
                url,
                headers={"Accept": "text/csv, text/plain, */*"},
            )
            if resp.status_code != 200:
                return None
            text = resp.text
    except Exception as exc:
        log.debug("usda_ers.csv_fail", url=url[-60:], error=str(exc)[:80])
        return None

    if not text or len(text) < 100:
        return None
    return text


async def _ensure_csvs() -> bool:
    """Download and parse ERS county CSVs once into in-memory caches."""
    global _RUCC_CACHE, _UNEMP_CACHE, _POVERTY_CACHE, _CSVS_LOADED
    if _CSVS_LOADED:
        return _RUCC_CACHE is not None
    _CSVS_LOADED = True

    # Download all three in parallel
    rucc_text, unemp_text, poverty_text = await asyncio.gather(
        _download_csv(RUCC_CSV_URL),
        _download_csv(UNEMP_CSV_URL),
        _download_csv(POVERTY_CSV_URL),
    )

    # Parse rural-urban continuum codes
    if rucc_text:
        _RUCC_CACHE = {}
        reader = csv.DictReader(io.StringIO(rucc_text))
        for row in reader:
            fips = (row.get("FIPS") or row.get("fips") or "").strip()
            if not fips or len(fips) < 5:
                continue
            _RUCC_CACHE[fips.zfill(5)] = {
                "rucc_code": _safe_int(row.get("Code") or row.get("RUCC")),
                "description": row.get("Description", "").strip(),
                "metro_nonmetro": (row.get("Metro") or row.get("metro") or "").strip(),
            }
        log.info("usda_ers.rucc_loaded", counties=len(_RUCC_CACHE))

    # Parse unemployment data
    if unemp_text:
        _UNEMP_CACHE = {}
        reader = csv.DictReader(io.StringIO(unemp_text))
        for row in reader:
            fips = (row.get("FIPS_Code") or row.get("fips") or "").strip()
            if not fips or len(fips) < 5:
                continue
            _UNEMP_CACHE[fips.zfill(5)] = {
                "unemployment_rate": _safe_float(
                    row.get("Unemployment_rate_2023")
                    or row.get("Unemployment_rate")
                    or row.get("unemployment_rate")
                ),
                "unemployed": _safe_int(row.get("Unemployed_2023")),
                "labor_force": _safe_int(row.get("Labor_force_2023")),
                "median_hh_income": _safe_int(row.get("Median_Household_Income")),
            }
        log.info("usda_ers.unemp_loaded", counties=len(_UNEMP_CACHE))

    # Parse poverty data
    if poverty_text:
        _POVERTY_CACHE = {}
        reader = csv.DictReader(io.StringIO(poverty_text))
        for row in reader:
            fips = (row.get("FIPS") or row.get("fips") or row.get("FIPS_Code") or "").strip()
            if not fips or len(fips) < 5:
                continue
            _POVERTY_CACHE[fips.zfill(5)] = {
                "poverty_rate": _safe_float(
                    row.get("PCTPOVALL_2023")
                    or row.get("poverty_rate")
                    or row.get("Poverty_rate")
                ),
                "poverty_count": _safe_int(
                    row.get("POVALL_2023") or row.get("poverty_count")
                ),
                "median_hh_income": _safe_int(
                    row.get("MEDHHINC_2023") or row.get("Median_HH_Income")
                ),
            }
        log.info("usda_ers.poverty_loaded", counties=len(_POVERTY_CACHE))

    return _RUCC_CACHE is not None


def _safe_float(val) -> float | None:
    if val is None or val == "" or val == "undefined":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


async def _query_usda_api(
    county_fips: str, api_key: str | None
) -> dict[str, Any] | None:
    """Query the USDA ERS API for county-level data (if key available)."""
    if not api_key:
        return None

    url = f"{USDA_API_BASE}/dataServices/v1/arms/reportData"
    try:
        async with client(timeout=15.0) as c:
            params: dict[str, str] = {
                "county_fips": county_fips,
                "format": "json",
            }
            if api_key:
                params["api_key"] = api_key
            resp = await c.get(
                url,
                params=params,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("usda_ers.api_fail", county=county_fips, error=str(exc)[:80])
        return None

    return data.get("results") if isinstance(data, dict) else None


async def enrich_usda_ers(listing: Listing) -> Listing:
    """Enrich a listing with USDA ERS county-level economic data."""
    raw_update: dict[str, Any] = {"economic": {}}

    # Get county FIPS from previous enrichment or construct from state+county
    raw = listing.raw if isinstance(listing.raw, dict) else {}
    county_fips = raw.get("county_fips")
    state_fips = raw.get("state_fips")

    if not county_fips:
        log.debug("usda_ers.no_fips", county=listing.county, state=listing.state)
        listing.raw = {**listing.raw, **raw_update}
        return listing

    fips = str(county_fips).zfill(5)

    # Look up from cached CSVs
    economic: dict[str, Any] = {"county_fips": fips, "source": "usda_ers"}

    if _RUCC_CACHE and fips in _RUCC_CACHE:
        rucc = _RUCC_CACHE[fips]
        economic["rucc_code"] = rucc.get("rucc_code")
        economic["rucc_description"] = rucc.get("description")
        economic["metro_nonmetro"] = rucc.get("metro_nonmetro")

    if _UNEMP_CACHE and fips in _UNEMP_CACHE:
        unemp = _UNEMP_CACHE[fips]
        economic["unemployment_rate"] = unemp.get("unemployment_rate")
        economic["unemployed"] = unemp.get("unemployed")
        economic["labor_force"] = unemp.get("labor_force")
        if unemp.get("median_hh_income"):
            economic["median_hh_income"] = unemp.get("median_hh_income")

    if _POVERTY_CACHE and fips in _POVERTY_CACHE:
        pov = _POVERTY_CACHE[fips]
        economic["poverty_rate"] = pov.get("poverty_rate")
        economic["poverty_count"] = pov.get("poverty_count")
        if pov.get("median_hh_income") and "median_hh_income" not in economic:
            economic["median_hh_income"] = pov.get("median_hh_income")

    # Also try the API if a key is available (may return ARMS survey data)
    api_key = _get_api_key()
    if api_key:
        api_data = await _query_usda_api(fips, api_key)
        if api_data:
            economic["api_data"] = api_data

    if len(economic) > 2:  # more than just fips + source
        raw_update["economic"] = economic

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_usda_ers(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with USDA ERS county-level economic data."""
    need_usda = [l for l in listings if "economic" not in (l.raw or {})]
    if not need_usda:
        return listings

    # Download CSVs once before processing
    await _ensure_csvs()

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_usda_ers(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_usda], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if "economic" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "usda_ers.batch_done",
        total=len(need_usda),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
