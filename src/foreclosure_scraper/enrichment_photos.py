"""Per-address photo gallery enrichment.

For listings sourced from courthouse rosters / law firms / sitemap walkers
(which give us address but no photos), this enrichment looks up the same
address on HomeHarvest's for_sale and sold endpoints to pull any active
or recent listing's photo gallery.

This is the "you said most listings have Zillow listings with interior photos"
fix — even if our scraper found the property via foreclosure courthouse
docket, the same property is usually ALSO on Realtor.com with rich photos.

Cost: $0. HomeHarvest hits Realtor.com's public API.
"""
from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# _by_address_lookup does up to 6 slow network+pandas HomeHarvest calls PER lead, so an
# uncapped board (1000s of leads/comps) makes this phase run for HOURS — the root cause of
# the overnight full-run not finishing. Cap leads enriched per call (highest distress-tier
# first); override via env for a supervised daytime run that wants fuller coverage.
#
# Photos are the UPSTREAM unlock for Vision: a lead with no photo can never be
# condition-graded, no matter how high VISION_MAX_LISTINGS goes. On the current
# board ~10.1k leads have an address but <3 photos while this cap only reached
# 500 of them per run (see logs/local-run-*: photos.capped processing=500
# skipped=9636) — a ~5% bite. Measured throughput is ~19 leads/min (500 leads in
# 26m34s on 4 threads), so the honest limiter here is TIME, not a count.
#
# So: the count cap goes to 2500 (high enough that it stops being the binding
# limiter) and a real wall-clock budget is added below. TRADEOFF: the phase now
# runs to its budget (~40 min) instead of stopping at ~26 min, and returns
# ~750-800 leads/run instead of 500. Lower FORECLOSURE_PHOTO_MAX_SECONDS to buy
# the time back; raise it on a supervised daytime run to go deeper.
_PHOTO_MAX_TARGETS = int(os.environ.get("FORECLOSURE_PHOTO_MAX_TARGETS") or "2500")
# HARD wall-clock bound on the phase. Checked per lead inside the worker, so
# after the deadline every remaining lead returns immediately and only the <=N
# already-in-flight lookups finish. 0 = unlimited (not recommended overnight).
# NOTE: the budget is PER CALL, not per process. main.run() calls this three
# times (active board, sold-comp pool, resolver catch-up), so the worst case
# for a full run is 3 x this value — in practice only the active-board call
# is big enough to reach the deadline (the other two run tens of leads).
_PHOTO_MAX_SECONDS = float(os.environ.get("FORECLOSURE_PHOTO_MAX_SECONDS") or "2400")
# Realtor.com's public API is free — keep the politeness ceiling low by default.
_PHOTO_WORKERS = int(os.environ.get("FORECLOSURE_PHOTO_WORKERS") or "4")


import re as _re


def _addr_signature(street: str | None) -> tuple[str, str]:
    """Return (house_number, normalized_street_keyword) for verification.
    Two listings match if both house number AND street keyword agree."""
    if not street:
        return ("", "")
    s = street.strip().lower()
    m = _re.match(r"^\s*(\d+)\s*", s)
    house = m.group(1) if m else ""
    # Normalize: drop leading number, drop directional + common suffixes
    s = _re.sub(r"^\d+\s*", "", s)
    s = _re.sub(
        r"\b(n|s|e|w|ne|nw|se|sw|north|south|east|west|"
        r"st|street|rd|road|ave|avenue|dr|drive|ln|lane|"
        r"ct|court|blvd|boulevard|hwy|highway|pl|place|way|trl|trail|"
        r"pkwy|parkway|cir|circle|terr|terrace|hl|hill)\b\.?",
        "", s,
    )
    s = _re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = [t for t in s.split() if len(t) > 2]
    keyword = max(tokens, key=len, default="")
    return (house, keyword)


def _addresses_match(requested_street: str, returned_street: str) -> bool:
    """Verify HomeHarvest returned the property we actually asked for.
    Avoids the silent-mismatch bug where HomeHarvest returns a NEAR address
    and we apply its photo to an unrelated listing.
    """
    if not requested_street or not returned_street:
        return False
    rh, rk = _addr_signature(requested_street)
    sh, sk = _addr_signature(returned_street)
    # Both house number AND street keyword must match
    if rh and sh and rh != sh:
        return False
    if rk and sk and rk != sk and rk not in sk and sk not in rk:
        return False
    return True


def _by_address_lookup(street: str, city: str, state: str, zip_code: str | None = None) -> Optional[dict]:
    """Look up a single address on HomeHarvest. Tries for_sale first
    (might be re-listed), then sold (most recent). Returns the row dict
    with primary_photo + alt_photos if found AND its address actually
    matches the requested street.
    """
    try:
        from homeharvest import scrape_property
    except ImportError:
        return None

    base_loc = f"{street}, {city}, {state}"
    if zip_code:
        full_loc = f"{base_loc} {zip_code}"
    else:
        full_loc = base_loc

    # Try multiple listing types — recent activity gives the richest photos
    for loc in [full_loc, base_loc]:
        for listing_type in ("for_sale", "pending", "sold"):
            try:
                df = scrape_property(
                    location=loc,
                    listing_type=listing_type,
                    past_days=730,  # 2-year window for sold history
                )
                if df is None or len(df) == 0:
                    continue
                # Verify each returned row's address matches what we asked
                # for. HomeHarvest sometimes returns near-matches when the
                # exact address isn't listed — without this check we'd apply
                # the wrong property's photo to multiple unrelated listings.
                for _, row in df.iterrows():
                    d = row.to_dict()
                    primary = d.get("primary_photo")
                    if not primary or (isinstance(primary, float) and primary != primary):
                        continue
                    returned_street = d.get("street") or d.get("full_street_line") or ""
                    if not _addresses_match(street, returned_street):
                        continue
                    return d
            except Exception:
                continue
    return None


def _photos_from_row(d: dict) -> list[str]:
    """Extract up to 6 photo URLs from a HomeHarvest row."""
    photos: list[str] = []
    primary = d.get("primary_photo") or ""
    if primary and not (isinstance(primary, float) and primary != primary):
        photos.append(str(primary))
    alt = d.get("alt_photos") or ""
    if isinstance(alt, str) and alt:
        photos.extend([p.strip() for p in alt.split(",") if p.strip()][:5])
    # Dedupe
    seen: set[str] = set()
    out: list[str] = []
    for p in photos:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _needs_photos(li: Listing) -> bool:
    """Listings worth enriching: have street_address + city + state but no real
    photos yet (or only the primary photo, no alt gallery)."""
    if not (li.street_address and li.city and li.state):
        return False
    raw = li.raw if isinstance(li.raw, dict) else {}
    images = raw.get("images") or {}
    zillow = raw.get("zillow") or {}
    real = images.get("real") or []
    z_photos = zillow.get("photos") or []
    # If we already have 3+ photos, skip
    n = max(
        len(real) if isinstance(real, list) else 0,
        len(z_photos) if isinstance(z_photos, list) else 0,
    )
    return n < 3


def _photo_priority(li: Listing) -> int:
    """Lower = enriched first when targets exceed the cap. HOT distress leads
    before WARM before everything else (comps/sold-pool rows rank last)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    tier = ((raw.get("distress_stack") or {}).get("tier")) or ""
    return {"HOT": 0, "WARM": 1}.get(tier, 2)


async def enrich_with_address_photos(listings: list[Listing]) -> None:
    """For listings without rich photo galleries, look up the address on
    HomeHarvest and pull primary + alt photos.

    Runs in a thread pool because HomeHarvest is sync. Bounded concurrency
    keeps Realtor's API friendly.
    """
    if not listings:
        return

    targets = [li for li in listings if _needs_photos(li)]
    if not targets:
        log.info("photos.no_targets")
        return

    # Bound runtime — HomeHarvest does up to 6 slow calls per lead. Process the
    # highest-priority leads first and cap; log the skip (never silently drop).
    # Sort ALWAYS (not just when over the count cap): the wall-clock deadline
    # below can cut the tail off even an under-cap batch, and when that happens
    # the leads that got done must be the HOT/WARM ones, not whatever order the
    # board happened to be in.
    all_needing = len(targets)
    targets.sort(key=_photo_priority)
    if all_needing > _PHOTO_MAX_TARGETS:
        targets = targets[:_PHOTO_MAX_TARGETS]
        log.info("photos.capped", processing=_PHOTO_MAX_TARGETS,
                 skipped=all_needing - _PHOTO_MAX_TARGETS, total_needing=all_needing)

    log.info("photos.start", target_count=len(targets), total=len(listings),
             budget_s=_PHOTO_MAX_SECONDS, workers=_PHOTO_WORKERS)

    loop = asyncio.get_event_loop()
    matched = 0
    # Wall-clock deadline. Enforced INSIDE the worker rather than by cancelling
    # the gather: these are thread-pool futures, and an abandoned gather would
    # still block on ThreadPoolExecutor shutdown until every queued lead ran.
    # Checking here makes post-deadline leads no-ops that drain instantly.
    deadline = (time.monotonic() + _PHOTO_MAX_SECONDS) if _PHOTO_MAX_SECONDS > 0 else None
    # list.append is atomic under the GIL — safe to count from worker threads.
    skipped_budget: list[int] = []

    def _process(li: Listing) -> int:
        if deadline is not None and time.monotonic() > deadline:
            skipped_budget.append(1)
            return 0
        d = _by_address_lookup(
            li.street_address, li.city, li.state, li.zip_code
        )
        if not d:
            return 0
        photos = _photos_from_row(d)
        if not photos:
            return 0
        if not isinstance(li.raw, dict):
            li.raw = {}
        images = li.raw.setdefault("images", {})
        zillow = li.raw.setdefault("zillow", {})
        # Merge with anything already there
        existing = images.get("real") if isinstance(images.get("real"), list) else []
        merged = list({u for u in (existing + photos) if u})
        images["real"] = merged[:6]
        # Also update zillow.photo + photos for legacy readers
        if not zillow.get("photo"):
            zillow["photo"] = photos[0]
        zillow["photos"] = (zillow.get("photos") or [])
        if isinstance(zillow["photos"], list):
            zillow["photos"] = list({u for u in (zillow["photos"] + photos) if u})[:6]
        # Backfill specs while we're here
        if li.living_sqft is None and d.get("sqft"):
            try:
                li.living_sqft = float(d["sqft"])
            except (TypeError, ValueError):
                pass
        if li.bedrooms is None and d.get("beds"):
            try:
                li.bedrooms = float(d["beds"])
            except (TypeError, ValueError):
                pass
        if li.bathrooms is None and d.get("full_baths"):
            try:
                li.bathrooms = float(d["full_baths"])
            except (TypeError, ValueError):
                pass
        if li.year_built is None and d.get("year_built"):
            yb = str(d["year_built"]).replace(".0", "")
            if yb.isdigit():
                li.year_built = int(yb)
        return 1

    with ThreadPoolExecutor(max_workers=_PHOTO_WORKERS) as pool:
        results = await asyncio.gather(
            *(loop.run_in_executor(pool, _process, li) for li in targets),
            return_exceptions=True,
        )
    matched = sum(r for r in results if isinstance(r, int))
    attempted = len(targets) - len(skipped_budget)
    log.info("photos.done", targets=len(targets), attempted=attempted,
             matched=matched, miss=max(attempted - matched, 0),
             skipped_budget=len(skipped_budget))
