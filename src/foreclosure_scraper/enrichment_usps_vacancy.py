"""USPS vacancy enrichment — HUD Aggregated USPS Administrative Data on Address Vacancies.

HUD receives quarterly aggregate data from USPS on addresses identified as
"Vacant" (not collecting mail for 90+ days) or "No-Stat". The data is
published at the ZIP-code and census-tract level, broken down by residential
and business addresses.

Source: https://www.huduser.gov/portal/datasets/usps.html

IMPORTANT: The USPS vacancy dataset is behind a registration wall — HUD
restricts access to governmental entities and non-profits with a "stated
purpose" sublicense agreement. The data is NOT freely downloadable without
logging in at https://www.huduser.gov/portal/usps/index.html.

This module supports TWO data ingestion modes:

1. MANUAL INGEST (default): The operator downloads the NC and SC vacancy
   data from the HUD USPS portal (after registering), exports to CSV, and
   places the files at the paths given by USPS_VACANCY_NC_CSV and
   USPS_VACANCY_SC_CSV env vars (or the default data/ paths). The module
   loads these files and flags leads by ZIP code.

2. API INGEST (if credentials provided): If USPS_HUD_TOKEN env var is set
   (a bearer token from a registered HUD USPS account), the module
   attempts to download state-level vacancy data via the HUD Neighborhood
   Change Web Map API at https://www.huduser.gov/apps/public/usps/.

Data structure (per the HUD data dictionary):
  - ZIP: 5-digit ZIP code
  - VACANT_RES: count of vacant residential addresses
  - VACANT_BUS: count of vacant business addresses
  - TOTAL_RES: total residential addresses
  - TOTAL_BUS: total business addresses
  - VACANT_RATE: VACANT_RES / TOTAL_RES (computed)
  - NO_STAT_RES: residential addresses classified as "No-Stat"
  - QUARTER: reporting quarter (e.g. "2024q4")

A ZIP code with a high residential vacancy rate (>5%) is a neighborhood-
distress signal — properties in these ZIPs are in areas with concentrated
abandonment, which increases re-sale difficulty and rehab risk.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

# --- configuration --------------------------------------------------------- #

_DATA_DIR = Path(
    os.environ.get(
        "FORECLOSURE_DATA_DIR",
        str(Path(__file__).resolve().parent / "data"),
    )
)

# Default CSV paths for manual ingest (operator places downloaded files here)
USPS_VACANCY_NC_CSV = Path(
    os.environ.get("USPS_VACANCY_NC_CSV", str(_DATA_DIR / "usps_vacancy_nc.csv"))
)
USPS_VACANCY_SC_CSV = Path(
    os.environ.get("USPS_VACANCY_SC_CSV", str(_DATA_DIR / "usps_vacancy_sc.csv"))
)

# HUD USPS API (requires registration token)
USPS_HUD_TOKEN = os.environ.get("USPS_HUD_TOKEN", "")
USPS_API_BASE = "https://www.huduser.gov/apps/public/usps"

# Vacancy rate thresholds for flagging
HIGH_VACANCY_THRESHOLD = 0.05   # 5% residential vacancy = high distress
MODERATE_VACANCY_THRESHOLD = 0.03  # 3% = moderate

# Cache the loaded vacancy data in memory across calls within a run
_vacancy_cache: dict[str, dict] | None = None


def _load_csv_vacancy(path: Path, state: str) -> dict[str, dict]:
    """Load a USPS vacancy CSV into a {zip_code: {fields}} dict.

    The CSV is expected to have at minimum a ZIP column and vacancy count
    columns. We compute a vacancy rate and classify the ZIP.
    """
    out: dict[str, dict] = {}
    if not path.exists():
        log.warning("usps_vacancy.csv_missing", path=str(path), state=state)
        return out

    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize column names (HUD exports vary in casing)
                row_lower = {k.lower().strip(): v for k, v in row.items()}

                # Try common ZIP column names
                zip_code = (
                    row_lower.get("zip")
                    or row_lower.get("zip_code")
                    or row_lower.get("zipcode")
                    or row_lower.get("zip5")
                    or ""
                ).strip()
                if not zip_code or len(zip_code) < 5:
                    continue
                zip_code = zip_code[:5]

                # Parse vacancy counts
                def _int(key: str) -> int:
                    v = row_lower.get(key, "0")
                    try:
                        return int(str(v).replace(",", "").strip() or "0")
                    except (ValueError, TypeError):
                        return 0

                vacant_res = _int("vacant_res")
                vacant_bus = _int("vacant_bus")
                total_res = _int("total_res") or _int("res_total") or _int("res")
                total_bus = _int("total_bus") or _int("bus_total") or _int("bus")
                no_stat_res = _int("no_stat_res") or _int("nostat_res")
                no_stat_bus = _int("no_stat_bus") or _int("nostat_bus")

                vac_rate = (vacant_res / total_res) if total_res > 0 else 0.0

                out[zip_code] = {
                    "zip": zip_code,
                    "state": state,
                    "vacant_res": vacant_res,
                    "vacant_bus": vacant_bus,
                    "total_res": total_res,
                    "total_bus": total_bus,
                    "no_stat_res": no_stat_res,
                    "no_stat_bus": no_stat_bus,
                    "vacant_rate": round(vac_rate, 4),
                    "quarter": row_lower.get("quarter") or row_lower.get("reporting_period") or "",
                    "source_file": path.name,
                }
    except (OSError, csv.Error) as exc:
        log.error("usps_vacancy.csv_read_error", path=str(path), error=str(exc)[:200])

    log.info("usps_vacancy.csv_loaded", path=str(path), state=state, zips=len(out))
    return out


async def _fetch_api_vacancy(state: str) -> dict[str, dict]:
    """Attempt to download vacancy data via the HUD USPS API.

    Requires USPS_HUD_TOKEN env var (from a registered account). Returns
    an empty dict if no token is set or the API is unreachable.
    """
    if not USPS_HUD_TOKEN:
        log.info("usps_vacancy.no_token", state=state)
        return {}

    out: dict[str, dict] = {}
    headers = {"Authorization": f"Bearer {USPS_HUD_TOKEN}"}

    # The HUD USPS API endpoint for state-level data downloads
    # (structure inferred from the NCWM web app's XHR calls)
    api_url = f"{USPS_API_BASE}/api/vacancy/{state.lower()}"

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as c:
            r = await c.get(api_url)
            if r.status_code != 200:
                log.warning(
                    "usps_vacancy.api_error",
                    state=state,
                    status=r.status_code,
                )
                return {}
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("usps_vacancy.api_fetch_error", state=state, error=str(exc)[:120])
        return {}

    records = data.get("data") or data.get("records") or []
    for rec in records:
        zip_code = str(rec.get("zip") or rec.get("zip_code") or "").strip()[:5]
        if not zip_code:
            continue
        vacant_res = int(rec.get("vacant_res", 0) or 0)
        total_res = int(rec.get("total_res", 0) or 0)
        vac_rate = (vacant_res / total_res) if total_res > 0 else 0.0
        out[zip_code] = {
            "zip": zip_code,
            "state": state,
            "vacant_res": vacant_res,
            "vacant_bus": int(rec.get("vacant_bus", 0) or 0),
            "total_res": total_res,
            "total_bus": int(rec.get("total_bus", 0) or 0),
            "no_stat_res": int(rec.get("no_stat_res", 0) or 0),
            "no_stat_bus": int(rec.get("no_stat_bus", 0) or 0),
            "vacant_rate": round(vac_rate, 4),
            "quarter": rec.get("quarter", ""),
            "source_file": f"api:{state}",
        }

    log.info("usps_vacancy.api_loaded", state=state, zips=len(out))
    return out


def _load_vacancy_data() -> dict[str, dict]:
    """Load vacancy data for NC and SC from CSV files or API.

    Merges both states into a single {zip: fields} dict. Cached in memory
    for the duration of the process.
    """
    global _vacancy_cache
    if _vacancy_cache is not None:
        return _vacancy_cache

    merged: dict[str, dict] = {}

    # Try CSV files first (manual ingest)
    for path, state in [(USPS_VACANCY_NC_CSV, "NC"), (USPS_VACANCY_SC_CSV, "SC")]:
        data = _load_csv_vacancy(path, state)
        if data:
            merged.update(data)

    # If no CSV data, try the API
    if not merged and USPS_HUD_TOKEN:
        for state in ("NC", "SC"):
            data = asyncio.get_event_loop().run_until_complete(
                _fetch_api_vacancy(state)
            ) if False else None  # API call is async; handled in enrich function
            # Note: the async API fetch is done in enrich_usps_vacancy below

    if not merged:
        log.warning(
            "usps_vacancy.no_data",
            hint="Download NC/SC vacancy CSVs from https://www.huduser.gov/portal/usps/ "
                 "and place at the configured paths, or set USPS_HUD_TOKEN for API access.",
            nc_path=str(USPS_VACANCY_NC_CSV),
            sc_path=str(USPS_VACANCY_SC_CSV),
        )

    _vacancy_cache = merged
    return merged


async def _load_vacancy_data_async() -> dict[str, dict]:
    """Async version: loads CSV data, then falls back to API if needed."""
    global _vacancy_cache
    if _vacancy_cache is not None:
        return _vacancy_cache

    merged: dict[str, dict] = {}

    # Try CSV files first
    for path, state in [(USPS_VACANCY_NC_CSV, "NC"), (USPS_VACANCY_SC_CSV, "SC")]:
        data = _load_csv_vacancy(path, state)
        if data:
            merged.update(data)

    # If no CSV data, try the API
    if not merged and USPS_HUD_TOKEN:
        for state in ("NC", "SC"):
            data = await _fetch_api_vacancy(state)
            merged.update(data)

    if not merged:
        log.warning(
            "usps_vacancy.no_data",
            hint="Download NC/SC vacancy CSVs from https://www.huduser.gov/portal/usps/ "
                 "and place at the configured paths, or set USPS_HUD_TOKEN for API access.",
            nc_path=str(USPS_VACANCY_NC_CSV),
            sc_path=str(USPS_VACANCY_SC_CSV),
        )

    _vacancy_cache = merged
    return merged


def _classify(vac_rate: float) -> str:
    """Classify a ZIP code's vacancy level."""
    if vac_rate >= HIGH_VACANCY_THRESHOLD:
        return "high"
    elif vac_rate >= MODERATE_VACANCY_THRESHOLD:
        return "moderate"
    elif vac_rate > 0:
        return "low"
    return "none"


async def enrich_usps_vacancy(listings: list[Listing]) -> dict:
    """Flag leads by ZIP code using USPS vacancy data.

    Writes to listing.raw['usps_vacancy'] = {
        zip, state, vacant_res, total_res, vacant_rate,
        vacancy_level: "high"|"moderate"|"low"|"none",
        quarter, source
    }

    Returns stats dict.
    """
    vacancy_data = await _load_vacancy_data_async()
    if not vacancy_data:
        log.info("usps_vacancy.skip_no_data")
        return {"flagged": 0, "high": 0, "moderate": 0, "total_zips": 0}

    stats = {"flagged": 0, "high": 0, "moderate": 0, "low": 0, "total_zips": len(vacancy_data)}

    for li in listings:
        zip_code = (li.zip_code or "").strip()[:5]
        if not zip_code:
            continue

        vac = vacancy_data.get(zip_code)
        if not vac:
            continue

        vac_rate = vac.get("vacant_rate", 0.0)
        level = _classify(vac_rate)

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["usps_vacancy"] = {
            "zip": zip_code,
            "state": vac.get("state"),
            "vacant_res": vac.get("vacant_res", 0),
            "total_res": vac.get("total_res", 0),
            "vacant_rate": vac_rate,
            "vacancy_level": level,
            "quarter": vac.get("quarter", ""),
            "source": vac.get("source_file", ""),
        }

        stats["flagged"] += 1
        if level == "high":
            stats["high"] += 1
        elif level == "moderate":
            stats["moderate"] += 1
        elif level == "low":
            stats["low"] += 1

    log.info("usps_vacancy.done", **stats)
    return stats


# --------------------------------------------------------------------------- #
# CSV template generator — creates a placeholder CSV with the expected columns
# --------------------------------------------------------------------------- #
def write_csv_template(path: Path) -> None:
    """Write a template CSV with the expected column headers.

    The operator fills this from the HUD USPS portal export.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ZIP", "VACANT_RES", "VACANT_BUS", "TOTAL_RES", "TOTAL_BUS",
            "NO_STAT_RES", "NO_STAT_BUS", "QUARTER",
        ])
        # Example row
        writer.writerow(["28801", "120", "5", "15000", "800", "30", "2", "2024q4"])
    log.info("usps_vacancy.template_written", path=str(path))


if __name__ == "__main__":
    import sys

    if "--template" in sys.argv:
        # Generate template CSVs
        write_csv_template(USPS_VACANCY_NC_CSV)
        write_csv_template(USPS_VACANCY_SC_CSV)
        print(f"Templates written to:\n  {USPS_VACANCY_NC_CSV}\n  {USPS_VACANCY_SC_CSV}")
        print("\nFill with data from https://www.huduser.gov/portal/usps/ (registration required)")
    else:
        # Test with sample data
        async def _test():
            data = await _load_vacancy_data_async()
            if not data:
                print("No vacancy data loaded. Run with --template to generate CSV templates.")
                return
            print(f"Loaded {len(data)} ZIP codes")
            # Show top 10 by vacancy rate
            top = sorted(data.values(), key=lambda x: x.get("vacant_rate", 0), reverse=True)[:10]
            for z in top:
                print(f"  {z['zip']} ({z['state']}): {z['vacant_rate']:.1%} vacant "
                      f"({z['vacant_res']}/{z['total_res']})")

        asyncio.run(_test())
