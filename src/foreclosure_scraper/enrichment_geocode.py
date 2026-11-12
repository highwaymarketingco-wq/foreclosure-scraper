"""Multi-tier geocoding cascade so 100% of listings get lat/lng.

Tier 1 — US Census Geocoder (free, fast, no rate limit, structured address)
Tier 2 — Nominatim (OpenStreetMap, rate-limited 1 req/sec, free-form address)
Tier 3 — City centroid (we already know the city + state)
Tier 4 — County-seat centroid (we always know the county)

Tiers 3 + 4 produce coarse lat/lng (off by miles) but they're enough for the
flood-zone API + dashboard map fallback to work — the alternative is a blank
no-image card.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import structlog

from .config import ALL_COUNTIES
from .http_client import client
from .models import Listing

log = structlog.get_logger()

NOMINATIM = "https://nominatim.openstreetmap.org/search"
CENSUS_GEO = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
UA = "ForeclosureScraperDashboard/1.0 (highwaymarketingco@gmail.com)"

_CACHE: dict[str, tuple[float, float] | None] = {}

# County-seat centroid table for the 21 counties we cover (lat, lng of county seat).
# Used as Tier-4 fallback when no address/city. Coarse but reliable.
COUNTY_SEAT_CENTROIDS: dict[tuple[str, str], tuple[float, float]] = {
    # SC
    ("SC", "Spartanburg"): (34.949, -81.932),
    ("SC", "Anderson"):    (34.504, -82.650),
    ("SC", "Pickens"):     (34.882, -82.706),
    ("SC", "Oconee"):      (34.764, -83.064),
    ("SC", "Cherokee"):    (35.072, -81.650),
    ("SC", "Union"):       (34.713, -81.624),
    ("SC", "Laurens"):     (34.499, -82.018),
    # NC
    ("NC", "Rutherford"):  (35.371, -81.957),
    ("NC", "Cleveland"):   (35.292, -81.535),
    ("NC", "Henderson"):   (35.318, -82.461),
    ("NC", "Polk"):        (35.252, -82.197),
    ("NC", "Gaston"):      (35.262, -81.187),
    ("NC", "Mecklenburg"): (35.227, -80.843),
    ("NC", "Buncombe"):    (35.595, -82.551),
    ("NC", "Transylvania"): (35.233, -82.734),
    ("NC", "McDowell"):    (35.674, -82.040),
    ("NC", "Lincoln"):     (35.470, -81.255),
    ("NC", "Madison"):     (35.825, -82.728),
    ("NC", "Yancey"):      (35.918, -82.299),
    ("NC", "Mitchell"):    (35.997, -82.143),
    ("NC", "Burke"):       (35.745, -81.685),
}

# 4 decimals (about 10 m): the fallback writes these exact 3-decimal values, while a real geocode
# that merely lies near a county seat carries more digits and is not mistaken for it.
_COUNTY_SEAT_POINTS = frozenset((round(a, 4), round(b, 4)) for a, b in COUNTY_SEAT_CENTROIDS.values())

#: raw['geo_imprecise'] values that describe a REAL resolved address, not a shared fallback point
#: (valuation/calc.py's _GEO_REAL_ADDRESS_TAGS, same reasoning).
_PRECISE_GEO_TAGS = ("census_geocode",)


def is_county_seat_point(lat, lng) -> bool:
    """(lat, lng) is this geocoder's Tier-4 fallback: a county seat from COUNTY_SEAT_CENTROIDS,
    shared by every lead of that county that had no usable address or city."""
    try:
        return (round(float(lat), 4), round(float(lng), 4)) in _COUNTY_SEAT_POINTS
    except (TypeError, ValueError):
        return False


def imprecise_point_flag(raw) -> bool:
    """The row's coordinate is flagged as a shared fallback, not its own location:
    raw['geo_imprecise'] set to anything but a real-address tag (centroid_snap from
    enrichment_board_quality, county_centroid / county_centroid_no_addr from the geocode scripts,
    a {'state': ...} dict from scripts/fill_*_gaps.py), or raw['geocoded_by_name']['approx'] (a
    city centroid for a named complex, enrichment_images)."""
    if not isinstance(raw, dict):
        return False
    gi = raw.get("geo_imprecise")
    tag = gi.get("state") if isinstance(gi, dict) else gi
    if tag and tag not in _PRECISE_GEO_TAGS:
        return True
    gbn = raw.get("geocoded_by_name")
    return isinstance(gbn, dict) and bool(gbn.get("approx"))


async def _census_geocode(c, address: str) -> Optional[tuple[float, float]]:
    """Tier 1: US Census Geocoder. Free, fast, no key."""
    try:
        r = await c.get(
            CENSUS_GEO,
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=15.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        matches = (data.get("result") or {}).get("addressMatches") or []
        if not matches:
            return None
        coords = matches[0].get("coordinates") or {}
        if "x" in coords and "y" in coords:
            return (float(coords["y"]), float(coords["x"]))
    except Exception:
        return None
    return None


async def _nominatim_geocode(c, query: str) -> Optional[tuple[float, float]]:
    """Tier 2: Nominatim. Free-form address, rate-limited."""
    try:
        r = await c.get(
            NOMINATIM,
            params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": UA},
            timeout=15.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data and isinstance(data, list):
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        return None
    return None



# ---------------------------------------------------------------------------
# Census BATCH pre-pass.
#
# Census was already tier 1 of the per-lead cascade, but it was being called one
# address at a time — 17,161 separate HTTP round-trips on the 2026-08-04 run,
# which is what burned the 600s budget and left 6,266 leads with no coordinates.
#
# The same free service accepts 10,000 addresses in ONE request. Running it as a
# pre-pass resolves the bulk in a handful of calls, so the rate-limited
# per-lead tier (Nominatim, 1 req/sec by their policy) only ever sees the tail.
# Nominatim's usage policy forbids bulk geocoding on the shared instance, so
# this is also the compliant way round: bulk goes to the service designed for it.
# ---------------------------------------------------------------------------
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
# The service DOCUMENTS 10,000 rows per file. In practice it 502s
# non-deterministically and size is not the variable: measured 2026-08-05,
# n=250 succeeded while n=100, n=500 and n=1000 all 502'd on the same data.
# So: modest chunks plus retry, which measured 832/1000 matched in 25s.
CENSUS_BATCH_MAX = int(os.environ.get("GEOCODE_CENSUS_BATCH_MAX", "250"))
CENSUS_BATCH_TRIES = int(os.environ.get("GEOCODE_CENSUS_BATCH_TRIES", "4"))
CENSUS_BATCH_TIMEOUT_S = float(os.environ.get("GEOCODE_CENSUS_BATCH_TIMEOUT_S", "180"))


def _batchable(li: Listing) -> bool:
    """Census batch needs a street plus enough locality to disambiguate."""
    return bool((li.street_address or "").strip()
                and ((li.city or "").strip() or (li.zip_code or "").strip())
                and (li.state or "").strip())


async def _census_batch(c, targets: list[Listing]) -> int:
    """Resolve as many targets as possible in bulk. Returns how many were filled."""
    import csv as _csv
    import io as _io

    rows = [li for li in targets if _batchable(li)]
    if not rows:
        return 0
    filled = 0
    for start in range(0, len(rows), CENSUS_BATCH_MAX):
        chunk = rows[start:start + CENSUS_BATCH_MAX]
        buf = _io.StringIO()
        w = _csv.writer(buf)
        for i, li in enumerate(chunk):
            w.writerow([i, (li.street_address or "").strip(), (li.city or "").strip(),
                        (li.state or "").strip(), (li.zip_code or "").strip()])
        r = None
        for attempt in range(CENSUS_BATCH_TRIES):
            try:
                r = await c.post(
                    CENSUS_BATCH_URL,
                    files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
                    data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
                    timeout=CENSUS_BATCH_TIMEOUT_S)
                if r.status_code == 200:
                    break
            except Exception as exc:  # noqa: BLE001
                log.warning("geocode.census_batch_error", chunk=start,
                            attempt=attempt + 1,
                            error=f"{type(exc).__name__}: {str(exc)[:80]}")
                r = None
            await asyncio.sleep(2 * (attempt + 1))
        if r is None or r.status_code != 200:
            log.warning("geocode.census_batch_giveup", chunk=start,
                        status=(r.status_code if r is not None else None),
                        tries=CENSUS_BATCH_TRIES)
            continue
        got = 0
        for line in _csv.reader(_io.StringIO(r.text)):
            # id, input, Match/No_Match, exactness, matched_addr, "lon,lat", ...
            if len(line) < 6 or line[2] != "Match":
                continue
            try:
                idx = int(line[0])
                lon, lat = (float(x) for x in line[5].split(","))
            except (ValueError, IndexError):
                continue
            if not (0 <= idx < len(chunk)):
                continue
            li = chunk[idx]
            if li.latitude is None or li.longitude is None:
                li.latitude, li.longitude = lat, lon
                filled += 1
                got += 1
        log.info("geocode.census_batch", chunk=start, sent=len(chunk), matched=got)
    return filled


async def _resolve(c, li: Listing, nominatim_delay: float,
                   fast_only: bool = False) -> Optional[tuple[float, float]]:
    """Cascade: Census -> Nominatim -> city centroid -> county centroid.

    fast_only (set once the run's geocode budget is spent): use only cached
    lookups + the instant county-seat centroid — no new network and no rate-limited
    Nominatim sleeps — so the loop can never run for hours.

    A row awaiting its parcel's point (enrichment_prior_correction.awaiting_parcel_point: the
    prior correction replaced the owner's mailing address on it and cleared the point geocoded
    from that address) is geocoded from its street only with a city or ZIP, and never gets a
    city or county-seat centroid: the correction leaves it without city/ZIP, so Tier 4 would put
    every one of them on the county seat, the shared fallback point of docs/HANDOFF.md item 70.
    It stays unplaced instead, for the parcel layer or a later run."""
    from .enrichment_prior_correction import awaiting_parcel_point
    hold = awaiting_parcel_point(li.raw)
    # Build candidate address strings from most specific to least
    candidates: list[str] = []
    if li.street_address and not (hold and not (li.city or li.zip_code)):
        bits = [li.street_address, li.city or "", f"{li.state or ''} {li.zip_code or ''}".strip()]
        candidates.append(", ".join(b for b in bits if b))
    if li.city and li.state and not hold:
        candidates.append(f"{li.city}, {li.state} {li.zip_code or ''}".strip())

    # Tier 1: Census geocoder (fast, no rate limit)
    for q in candidates:
        cache_key = f"census:{q}"
        if cache_key in _CACHE:
            res = _CACHE[cache_key]
        elif fast_only:
            continue  # budget spent — no new network; fall through to centroid
        else:
            res = await _census_geocode(c, q)
            _CACHE[cache_key] = res
        if res:
            return res

    # Tier 2: Nominatim (rate-limited) — skipped entirely once budget is spent
    if not fast_only:
        for q in candidates:
            cache_key = f"nominatim:{q}"
            if cache_key in _CACHE:
                res = _CACHE[cache_key]
            else:
                res = await _nominatim_geocode(c, q)
                _CACHE[cache_key] = res
                await asyncio.sleep(nominatim_delay)
            if res:
                return res

    if hold:
        return None  # no centroid tiers for a row awaiting its parcel's point (docstring)

    # Tier 3: city centroid via Census (just city + state, no street)
    if li.city and li.state:
        q = f"{li.city}, {li.state}"
        cache_key = f"city:{q}"
        if cache_key in _CACHE:
            res = _CACHE[cache_key]
        elif fast_only:
            res = None  # budget spent — skip network, fall through to centroid
        else:
            res = await _census_geocode(c, q) or await _nominatim_geocode(c, q)
            _CACHE[cache_key] = res
            await asyncio.sleep(nominatim_delay)
        if res:
            return res

    # Tier 4: county-seat centroid (always works for listings in our scope)
    if li.state and li.county:
        # Normalize county name (strip "County")
        c_name = li.county.replace(" County", "").strip()
        return COUNTY_SEAT_CENTROIDS.get((li.state, c_name))

    return None


async def enrich(listings: list[Listing], rate_per_sec: float = 1.0) -> list[Listing]:
    """Multi-tier geocoder. Goal: 100% of listings get lat/lng (coarse OK), except a row awaiting
    its parcel's point (see _resolve): the parcel layer or its corrected street, or nothing."""
    from .enrichment_prior_correction import awaiting_parcel_point, mark_point_placed, place_parcel_points
    for li in listings:
        # placed since the correction by an earlier phase (the GIS phase's parcel centroid)
        if li.latitude is not None and li.longitude is not None and awaiting_parcel_point(li.raw):
            mark_point_placed(li, "before_geocode")
    targets = [li for li in listings if li.latitude is None or li.longitude is None]
    if not targets:
        return listings

    # Hard wall-clock budget on the RATE-LIMITED tiers. Nominatim sleeps 1s/lead,
    # so thousands of address-less / name-only leads would otherwise stall the run
    # for hours (observed: 8.5h full-run hang). Once the budget is spent, remaining
    # leads skip Census/Nominatim network and take the instant county-seat centroid.
    budget_s = float(os.environ.get("GEOCODE_BUDGET_S", "600"))
    t0 = time.monotonic()
    budget_hit = False

    waiting = [li for li in targets if awaiting_parcel_point(li.raw)]

    async with client(timeout=20.0) as c:
        # Rows whose carried point the prior correction cleared (it was geocoded from the owner's
        # mailing address shown as the property): the parcel's own polygon first, from the
        # county layer, by parcel id (enrichment_prior_correction.place_parcel_points).
        if waiting:
            pp = await place_parcel_points(c, waiting)
            log.info("geocode.parcel_points", awaiting=len(waiting), **dict(pp))
            targets = [li for li in targets if li.latitude is None or li.longitude is None]
        # Bulk first, so the rate-limited per-lead tier only sees what is left.
        batch_filled = await _census_batch(c, targets)
        targets = [li for li in targets
                   if li.latitude is None or li.longitude is None]

        delay = max(1.0 / rate_per_sec, 1.0)
        matched = batch_filled
        for li in targets:
            if not budget_hit and time.monotonic() - t0 > budget_s:
                budget_hit = True
                log.warning("geocode.budget_hit", budget_s=budget_s,
                            elapsed_s=round(time.monotonic() - t0))
            res = await _resolve(c, li, delay, fast_only=budget_hit)
            if res:
                li.latitude, li.longitude = res
                matched += 1

    unplaced = 0
    for li in waiting:
        if li.latitude is not None and li.longitude is not None:
            if awaiting_parcel_point(li.raw):
                mark_point_placed(li, "geocode")     # the corrected street, with its city/ZIP
        else:
            unplaced += 1
    if waiting:
        log.info("geocode.awaiting_parcel_point_unplaced", rows=unplaced,
                 note="left without a point rather than on a city or county-seat centroid")

    final_missing = sum(1 for li in listings if li.latitude is None or li.longitude is None)
    log.info("geocode.done",
             queried=len(targets), matched=matched, batch_filled=batch_filled,
             budget_hit=budget_hit,
             total=len(listings), still_missing=final_missing)
    return listings
