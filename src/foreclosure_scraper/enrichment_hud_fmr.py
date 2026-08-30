"""HUD Fair Market Rent (FMR) enricher — uses HUD REST API with token.

Uses the HUD FMR & Income Limits Data API (free, requires token from huduser.gov).
Token stored in .env as HUD_API_TOKEN.

API endpoints:
  - fmr/statedata/{statecode}  → all metro FMR data for a state
  - fmr/listCounties/{state}   → county FIPS codes
  - fmr/data/{entityid}        → single area FMR data

Strategy:
  1. Fetch listCounties for NC + SC → build county FIPS → rent mapping
  2. Fetch statedata for NC + SC → build metro area → rent mapping
  3. For each listing, match by county FIPS (from li.county + li.state)
  4. Fallback: match by metro area name
  5. Cache to data/hud_fmr_cache.json (30-day TTL)

FMRs are published by metro area and non-metro county. This replaces
the Census ACS rent data (which also needs an API key).
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Sequence

import structlog

from .models import Listing

log = structlog.get_logger()

_CACHE_DIR = Path(
    os.environ.get("FMR_CACHE", str(Path(__file__).parent.parent.parent / "data" / "fmr_cache"))
)
_CACHE_FILE = _CACHE_DIR / "fmr_by_county.json"

_API_BASE = "https://www.huduser.gov/hudapi/public/fmr"

# NC + SC states we cover
_STATES = ["NC", "SC"]

# County name → FIPS prefix mapping (state → {county_name_lower → fips_prefix})
# We build this from the listCounties API response.
_county_fips_map: dict[str, dict[str, str]] = {}

# Metro area → rent data mapping
_metro_rent_map: dict[str, dict] = {}

# County FIPS → rent data mapping (most precise)
_county_rent_map: dict[str, dict] = {}

_loaded = False


def _get_token() -> str | None:
    """Read HUD API token from .env or env."""
    # Try env first
    token = os.environ.get("HUD_API_TOKEN", "")
    if token:
        return token.strip().strip('"').strip("'")

    # Walk up from this file to find .env
    # File: src/foreclosure_scraper/enrichment_hud_fmr.py → project root is 3 parents up
    p = Path(__file__).resolve().parent.parent.parent  # project root
    for env_path in [p / ".env", p.parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("HUD_API_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if token:
                        return token
    return None


def _api_get(path: str) -> dict | list | None:
    """Make authenticated GET to HUD API."""
    import urllib.request

    token = _get_token()
    if not token:
        log.error("hud_fmr.no_token")
        return None

    url = f"{_API_BASE}/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
    })
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            if resp.status != 200:
                log.warn("hud_fmr.api_status", url=url, status=resp.status)
                return None
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        log.warn("hud_fmr.api_error", url=url, error=str(e)[:120])
        return None


def _load_fmr_data() -> dict[str, dict]:
    """Load FMR data from cache or HUD API.

    Returns dict: {county_fips: {efficiency, 1br, 2br, 3br, 4br, year, area_name}}
    """
    global _loaded, _county_rent_map, _metro_rent_map, _county_fips_map

    if _loaded:
        return _county_rent_map

    # Try cache first
    if _CACHE_FILE.exists():
        mtime = _CACHE_FILE.stat().st_mtime
        age_days = (datetime.now().timestamp() - mtime) / 86400
        if age_days < 30:
            try:
                with open(_CACHE_FILE) as f:
                    cached = json.load(f)
                _county_rent_map = cached.get("county_rent", {})
                _metro_rent_map = cached.get("metro_rent", {})
                _county_fips_map = cached.get("county_fips", {})
                _loaded = True
                log.info("hud_fmr.cache_loaded",
                         counties=len(_county_rent_map),
                         metros=len(_metro_rent_map),
                         age_days=round(age_days, 1))
                return _county_rent_map
            except Exception:
                pass

    # Fetch from HUD API
    log.info("hud_fmr.fetching_from_api")

    for state in _STATES:
        # 1. Get state-level metro area data (1 API call gets ALL areas)
        state_data = _api_get(f"statedata/{state}")
        if state_data and isinstance(state_data, dict):
            metros = state_data.get("data", {}).get("metroareas", [])
            for m in metros:
                code = m.get("code", "")
                metro_name = m.get("metro_name", "")
                if code:
                    rent = {
                        "efficiency": _safe_int(m.get("Efficiency")),
                        "1br": _safe_int(m.get("One-Bedroom")),
                        "2br": _safe_int(m.get("Two-Bedroom")),
                        "3br": _safe_int(m.get("Three-Bedroom")),
                        "4br": _safe_int(m.get("Four-Bedroom")),
                        "year": str(m.get("year", state_data.get("data", {}).get("year", "2026"))),
                        "area_name": metro_name,
                    }
                    _metro_rent_map[code] = rent
                    # Also index by county name extracted from metro_name
                    # e.g. "Anson County, NC HUD Metro FMR Area" → "anson"
                    if "County" in metro_name:
                        county_key = metro_name.split(" County")[0].lower().strip()
                        _county_fips_map.setdefault(state, {})[county_key] = code
            log.info("hud_fmr.state_metros", state=state, metros=len(metros))

        # 2. Get county FIPS codes (for matching)
        counties = _api_get(f"listCounties/{state}")
        if not counties or not isinstance(counties, list):
            log.warn("hud_fmr.no_counties", state=state)
            continue

        state_map = _county_fips_map.get(state, {})
        for c in counties:
            fips = str(c.get("fips_code", ""))
            name = str(c.get("county_name", "")).lower().replace(" county", "").strip()
            if fips and name and name not in state_map:
                state_map[name] = fips
        _county_fips_map[state] = state_map
        log.info("hud_fmr.state_counties", state=state, fips_codes=len(state_map))

    # 3. Fetch non-metro county FMR data (FIPS codes ending in 9999)
    #    These are rural counties not covered by metro areas
    import time as _time
    non_metro = []
    for state, cmap in _county_fips_map.items():
        for county, code in cmap.items():
            if not code.startswith("METRO") and code not in _county_rent_map:
                non_metro.append((state, county, code))
    log.info("hud_fmr.fetching_non_metro", count=len(non_metro))
    for state, county, fips in non_metro:
        resp = _api_get(f"data/{fips}")
        if resp and isinstance(resp, dict):
            data_obj = resp.get("data")
            if isinstance(data_obj, dict):
                bd = data_obj.get("basicdata")
                if isinstance(bd, dict) and bd.get("Three-Bedroom"):
                    _county_rent_map[fips] = {
                        "efficiency": _safe_int(bd.get("Efficiency")),
                        "1br": _safe_int(bd.get("One-Bedroom")),
                        "2br": _safe_int(bd.get("Two-Bedroom")),
                        "3br": _safe_int(bd.get("Three-Bedroom")),
                        "4br": _safe_int(bd.get("Four-Bedroom")),
                        "year": str(bd.get("year", "2026")),
                        "area_name": data_obj.get("area_name", ""),
                    }
        _time.sleep(1.0)  # HUD rate limit: ~1 req/sec
    log.info("hud_fmr.non_metro_done", fetched=len(_county_rent_map))

    # Save cache
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump({
                "county_rent": _county_rent_map,
                "metro_rent": _metro_rent_map,
                "county_fips": _county_fips_map,
                "cached_at": datetime.now().isoformat(),
            }, f)
        log.info("hud_fmr.cache_saved", path=str(_CACHE_FILE),
                 counties=len(_county_rent_map), metros=len(_metro_rent_map))
    except Exception as e:
        log.warn("hud_fmr.cache_save_failed", error=str(e))

    _loaded = True
    return _county_rent_map


def _safe_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(str(v).replace("$", "").replace(",", "")))
    except (ValueError, TypeError):
        return None


def _match_listing_to_fmr(li: Listing) -> dict | None:
    """Match a listing to FMR data by county or metro area."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Try county FIPS match first (most precise)
    state = li.state or raw.get("state", "")
    county = li.county or raw.get("county", "")
    if state and county:
        county_lower = county.lower().replace(" county", "").strip()
        state_map = _county_fips_map.get(state, {})
        code = state_map.get(county_lower)
        if code:
            # If it's a metro code, look up in metro_rent_map
            if code in _metro_rent_map:
                return _metro_rent_map[code]
            # If it's a county FIPS code, look up in county_rent_map
            if code in _county_rent_map:
                return _county_rent_map[code]

    # Fallback: try metro area match by county name
    if county:
        county_lower = county.lower().replace(" county", "").strip()
        for mcode, rent in _metro_rent_map.items():
            area = rent.get("area_name", "").lower()
            if county_lower in area:
                return rent

    return None


def _pick_fmr(rent_data: dict, bedrooms: int | None) -> dict | None:
    """Pick the right FMR tier based on bedrooms."""
    if not rent_data:
        return None

    if bedrooms is not None:
        if bedrooms <= 0:
            rent = rent_data.get("efficiency") or rent_data.get("1br")
        elif bedrooms == 1:
            rent = rent_data.get("1br") or rent_data.get("efficiency")
        elif bedrooms == 2:
            rent = rent_data.get("2br") or rent_data.get("1br")
        elif bedrooms == 3:
            rent = rent_data.get("3br") or rent_data.get("2br")
        else:
            rent = rent_data.get("4br") or rent_data.get("3br")
    else:
        rent = rent_data.get("3br") or rent_data.get("2br") or rent_data.get("1br")

    if not rent:
        return None

    return {
        "fmr_monthly": rent,
        "fmr_br_tier": f"{bedrooms or 3}br" if bedrooms else "3br_default",
        "fmr_all_tiers": {
            "efficiency": rent_data.get("efficiency"),
            "1br": rent_data.get("1br"),
            "2br": rent_data.get("2br"),
            "3br": rent_data.get("3br"),
            "4br": rent_data.get("4br"),
        },
        "fmr_year": rent_data.get("year", "2026"),
        "fmr_area": rent_data.get("area_name", ""),
    }


async def enrich_hud_fmr(listings: Sequence[Listing]) -> dict:
    """Enrich listings with HUD Fair Market Rent data via HUD API.

    Requires HUD_API_TOKEN in .env (free from huduser.gov).
    """
    stats = {
        "total": 0,
        "listings_with_rent": 0,
        "matched_county": 0,
        "matched_metro": 0,
        "no_match": 0,
        "already_had_rent": 0,
    }

    # Load FMR data (from cache or API)
    try:
        fmr_data = await asyncio.to_thread(_load_fmr_data)
        log.info("hud_fmr.data_ready",
                 counties=len(_county_rent_map),
                 metros=len(_metro_rent_map))
    except Exception as e:
        log.error("hud_fmr.load_failed", error=str(e))
        stats["error"] = str(e)
        return stats

    if not _county_rent_map and not _metro_rent_map:
        log.error("hud_fmr.no_data_loaded")
        stats["error"] = "No FMR data loaded — check HUD_API_TOKEN"
        return stats

    for li in listings:
        stats["total"] += 1
        raw = li.raw if isinstance(li.raw, dict) else {}

        # Skip if already has rent estimate
        if raw.get("hud_fmr") or raw.get("census_rent"):
            stats["already_had_rent"] += 1
            continue

        rent_data = _match_listing_to_fmr(li)
        if not rent_data:
            stats["no_match"] += 1
            continue

        bedrooms = int(li.bedrooms) if li.bedrooms else None
        fmr_info = _pick_fmr(rent_data, bedrooms)
        if fmr_info:
            raw["hud_fmr"] = fmr_info
            # Also set census_rent so downstream enrichers pick it up
            if not raw.get("census_rent"):
                raw["census_rent"] = {
                    "monthly_rent": fmr_info["fmr_monthly"],
                    "source": "hud_fmr_api",
                    "br_tier": fmr_info["fmr_br_tier"],
                    "area": fmr_info["fmr_area"],
                }
            stats["listings_with_rent"] += 1
            if rent_data in _county_rent_map.values():
                stats["matched_county"] += 1
            else:
                stats["matched_metro"] += 1
        else:
            stats["no_match"] += 1

    log.info(
        "hud_fmr.complete",
        total=stats["total"],
        matched=stats["listings_with_rent"],
        no_match=stats["no_match"],
        already_had=stats["already_had_rent"],
    )

    return stats
