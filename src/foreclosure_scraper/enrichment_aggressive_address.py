"""Aggressive address resolution — last-resort path for listings still
missing an address after all earlier enrichments.

Cascade applied per listing:

  1. Parcel/PIN/REID lookup — handled by enrichment_parcel_lookup.py first
  2. Owner-name lookup in the listing's stated county (handled by
     enrichment_address_backfill.py)
  3. Owner-name lookup across ALL counties in the listing's state
     (this enrichment) — for listings where the county field is wrong
     or the owner moved counties
  4. HomeHarvest by owner — Realtor.com sometimes indexes properties by
     owner / agent / contact information
  5. Fuzzy partial-token match in stated county GIS — drops the strict
     "all distinctive tokens must match" tie-breaker for cases where
     the defendant name is a partial form

Runs LAST, only on listings still without street_address.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx
import structlog

from .enrichment_address_backfill import (
    _OWNER_FIELD_CANDIDATES,
    _BUSINESS_STOPWORDS,
    _defendant_search_terms,
    _detect_owner_field,
    _populate_from_attrs,
    _query_by_owner,
)
from .enrichment_arcgis import (
    FIELD_ALIASES,
    NC_GIS,
    SC_LAYER,
    SCDOT_BASE,
    _pick,
)
from .http_client import client
from .models import Listing

log = structlog.get_logger()


# SC case# prefix → county. Authoritative for venue.
_SC_COUNTY_BY_CODE = {
    "01": "Abbeville", "02": "Aiken", "03": "Allendale", "04": "Anderson",
    "05": "Bamberg", "06": "Barnwell", "07": "Beaufort", "08": "Berkeley",
    "09": "Calhoun", "10": "Charleston", "11": "Cherokee", "12": "Chester",
    "13": "Chesterfield", "14": "Clarendon", "15": "Colleton", "16": "Darlington",
    "17": "Dillon", "18": "Dorchester", "19": "Edgefield", "20": "Fairfield",
    "21": "Florence", "22": "Georgetown", "23": "Greenville", "24": "Greenwood",
    "25": "Hampton", "26": "Horry", "27": "Jasper", "28": "Kershaw",
    "29": "Lancaster", "30": "Laurens", "31": "Lee", "32": "Lexington",
    "33": "Marion", "34": "Marlboro", "35": "McCormick", "36": "Newberry",
    "37": "Oconee", "38": "Orangeburg", "39": "Pickens", "40": "Richland",
    "41": "Saluda", "42": "Spartanburg", "43": "Sumter", "44": "Union",
    "45": "Williamsburg", "46": "York",
}

_SC_CASE_RE = re.compile(r"(\d{4})-CP-(\d{2})-\d+")


def _case_pins_county(li: Listing) -> bool:
    """Return True when the listing's case number authoritatively encodes a
    county (so any same-name GIS match in a different county must not rewrite
    li.county). Currently covers SC Common Pleas case numbers."""
    if not li.case_number:
        return False
    if li.state == "SC":
        m = _SC_CASE_RE.match(li.case_number.strip())
        if m and m.group(2) in _SC_COUNTY_BY_CODE:
            return True
    return False


def _all_county_endpoints_for_state(state: str) -> list[tuple[str, str]]:
    """Return (county_name, base_url) for every GIS we have for this state."""
    out: list[tuple[str, str]] = []
    if state == "NC":
        for county, cfg in NC_GIS.items():
            out.append((county, cfg["url"]))
    elif state == "SC":
        for county, layer in SC_LAYER.items():
            out.append((county, f"{SCDOT_BASE}/{layer}/query"))
    return out


async def _aggressive_owner_search(
    c: httpx.AsyncClient,
    li: Listing,
    owner_field_cache: dict[str, Optional[str]],
) -> Optional[dict[str, Any]]:
    """Try every county GIS in the listing's state. Take first single-result hit.
    Tight per-county timeout so a single slow GIS doesn't hang the whole search.
    """
    state = li.state
    if state not in ("NC", "SC"):
        return None
    if not li.defendant:
        return None

    name = re.sub(r",\s*Personal\s+Representative.*$", "", li.defendant, flags=re.I)
    name = re.sub(r",\s*et\s*al\.?.*$", "", name, flags=re.I).strip()
    if not name:
        return None

    endpoints = _all_county_endpoints_for_state(state)

    # Skip the county we already tried in the address_backfill pass
    if li.county:
        already = li.county.replace(" County", "").strip().title()
        endpoints = [(c, u) for c, u in endpoints if c != already]

    for county_name, base in endpoints:
        try:
            if base not in owner_field_cache:
                owner_field_cache[base] = await asyncio.wait_for(
                    _detect_owner_field(c, base), timeout=8.0,
                )
            owner_field = owner_field_cache[base]
            if not owner_field:
                continue
            results = await asyncio.wait_for(
                _query_by_owner(c, base, owner_field, name), timeout=10.0,
            )
        except (asyncio.TimeoutError, Exception):
            continue
        if not results:
            continue
        if len(results) == 1:
            attrs = results[0]
            attrs["_matched_county"] = county_name
            return attrs
        d_tokens = {
            t for t in re.split(r"\W+", name.lower())
            if len(t) >= 3 and t not in _BUSINESS_STOPWORDS
        }
        for r in results:
            owner = (_pick(r, FIELD_ALIASES["owner_name"]) or "").lower()
            if d_tokens and all(t in owner for t in d_tokens):
                r["_matched_county"] = county_name
                return r
    return None


async def _fuzzy_partial_search(
    c: httpx.AsyncClient,
    li: Listing,
    owner_field_cache: dict[str, Optional[str]],
) -> Optional[dict[str, Any]]:
    """Loosened tie-break for the listing's own county: accept 2+ matching
    distinctive tokens (instead of requiring ALL).
    """
    if not (li.defendant and li.county and li.state):
        return None
    county_clean = li.county.replace(" County", "").strip().title()
    if li.state == "NC":
        cfg = NC_GIS.get(county_clean)
        if not cfg:
            return None
        base = cfg["url"]
    elif li.state == "SC":
        layer = SC_LAYER.get(county_clean)
        if not layer:
            return None
        base = f"{SCDOT_BASE}/{layer}/query"
    else:
        return None

    if base not in owner_field_cache:
        owner_field_cache[base] = await _detect_owner_field(c, base)
    owner_field = owner_field_cache[base]
    if not owner_field:
        return None

    name = re.sub(r",\s*Personal\s+Representative.*$", "", li.defendant, flags=re.I)
    name = re.sub(r",\s*et\s*al\.?.*$", "", name, flags=re.I).strip()
    results = await _query_by_owner(c, base, owner_field, name)
    if not results or len(results) > 20:
        return None

    d_tokens = {
        t for t in re.split(r"\W+", name.lower())
        if len(t) >= 3 and t not in _BUSINESS_STOPWORDS
    }
    if len(d_tokens) < 2:
        return None
    # Partial match: best score >= 2 tokens
    best, best_score = None, 0
    for r in results:
        owner = (_pick(r, FIELD_ALIASES["owner_name"]) or "").lower()
        score = sum(1 for t in d_tokens if t in owner)
        if score > best_score:
            best_score = score
            best = r
    if best and best_score >= 2:
        return best
    return None


async def enrich_with_aggressive_address(listings: list[Listing]) -> None:
    """Last-resort address recovery — HARD-CAPPED.

    Cost math that motivates the caps below:
      For each unaddressed listing, this enrichment hits every county GIS
      in the listing's state (NC=14 counties, SC=46 counties), and for each
      county runs 3 owner-name search permutations (multi-token, reversed,
      single-longest-token). With 100+ unaddressed listings × 46 SC layers
      × 3 permutations = 13,800+ HTTP queries. Even at 0.5s each that's
      almost 2 hours, and many GIS endpoints take 1-3s.

      Run #16 hit this exact failure mode: aggressive_address ran 3h 21m
      on a single step before user cancelled. There was no wall-clock
      cap, no per-listing timeout, no max-targets cap.

    Caps now enforced:
      * MAX_TARGETS — at most this many listings get the aggressive
        treatment per run (highest-priority by sale_date / opening_bid).
      * WALL_CLOCK_LIMIT_S — total wall-clock budget for this enrichment.
        On expiry, every in-flight task is cancelled cleanly and the
        pipeline moves on; partial successes are kept.
      * PER_LISTING_TIMEOUT_S — single listing can't burn more than this.

    Tunable via env vars: AGGRESSIVE_ADDR_MAX_TARGETS,
    AGGRESSIVE_ADDR_WALL_CLOCK_S, AGGRESSIVE_ADDR_PER_LISTING_S.
    """
    import os
    from datetime import datetime as _dt

    MAX_TARGETS = int(os.environ.get("AGGRESSIVE_ADDR_MAX_TARGETS", "30"))
    WALL_CLOCK_LIMIT_S = float(os.environ.get("AGGRESSIVE_ADDR_WALL_CLOCK_S", "480"))
    PER_LISTING_TIMEOUT_S = float(os.environ.get("AGGRESSIVE_ADDR_PER_LISTING_S", "30"))

    targets = [
        li for li in listings
        if not li.street_address
        and li.state in ("NC", "SC")
        and li.defendant
        and li.source != "national.courtlistener_bankruptcy"
    ]
    if not targets:
        log.info("aggressive_addr.no_targets")
        return

    # Prioritize: soonest-sale-date first, then highest opening_bid. The
    # cap is a budget, so we want the listings most likely to matter.
    targets.sort(key=lambda li: (
        li.sale_date or _dt.max,
        -(li.opening_bid or 0.0),
    ))

    total_targets = len(targets)
    if len(targets) > MAX_TARGETS:
        log.warning(
            "aggressive_addr.target_cap_applied",
            had=len(targets), keeping=MAX_TARGETS,
            note="prioritized by soonest-sale and highest-bid",
        )
        targets = targets[:MAX_TARGETS]

    log.info(
        "aggressive_addr.start",
        target_count=len(targets),
        of_total=total_targets,
        wall_clock_limit_s=WALL_CLOCK_LIMIT_S,
        per_listing_timeout_s=PER_LISTING_TIMEOUT_S,
    )

    sem = asyncio.Semaphore(4)
    cache: dict[str, Optional[str]] = {}
    counts = {
        "queried": 0,
        "all_state_match": 0,
        "fuzzy_partial_match": 0,
        "no_match": 0,
        "per_listing_timeout": 0,
        "wall_clock_cancelled": 0,
    }

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        async with sem:
            counts["queried"] += 1
            try:
                # Per-listing timeout: each listing gets at most this much
                # wall-clock budget. Without this, ONE slow GIS could
                # monopolize the run (and they often do — SCDOT's MapServer
                # 4 has been observed at 30+s per query during business
                # hours).
                await asyncio.wait_for(
                    _run_one_listing(c, li, cache, counts),
                    timeout=PER_LISTING_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                counts["per_listing_timeout"] += 1
                log.debug(
                    "aggressive_addr.per_listing_timeout",
                    case=li.case_number, defendant=li.defendant,
                )
            except asyncio.CancelledError:
                counts["wall_clock_cancelled"] += 1
                raise

    async with client(timeout=20.0) as c:
        try:
            await asyncio.wait_for(
                asyncio.gather(*(one(c, li) for li in targets)),
                timeout=WALL_CLOCK_LIMIT_S,
            )
        except asyncio.TimeoutError:
            log.warning(
                "aggressive_addr.wall_clock_exceeded",
                limit_s=WALL_CLOCK_LIMIT_S,
                queried_so_far=counts["queried"],
                completed=counts["all_state_match"] + counts["fuzzy_partial_match"],
            )

    log.info("aggressive_addr.done", **counts)


async def _run_one_listing(
    c: httpx.AsyncClient,
    li: Listing,
    cache: dict[str, Optional[str]],
    counts: dict[str, int],
) -> None:
    """Single-listing body extracted so it can be wrapped with a per-listing
    timeout cleanly."""
    # If the case number authoritatively pins the property's county
    # (SC lis pendens case numbers always do — venue follows situs by
    # statute), skip the cross-county scan entirely. A same-name owner
    # match in any other county is by definition the wrong person /
    # wrong parcel for this case. The previous-tier address_backfill
    # enrichment already searched the pinned county; if it didn't
    # match there, no amount of scanning *other* counties helps.
    case_pinned = _case_pins_county(li)

    # Tier A: scan all counties in state — skipped when case-pinned
    if not case_pinned:
        attrs = await _aggressive_owner_search(c, li, cache)
        if attrs:
            if attrs.get("_matched_county") and not li.street_address:
                li.county = attrs["_matched_county"]
            _populate_from_attrs(li, attrs)
            if li.street_address:
                counts["all_state_match"] += 1
                return

    # Tier B: fuzzy partial match in stated county (always safe — same
    # county as the listing's case-pinned or scraper-assigned tag)
    attrs = await _fuzzy_partial_search(c, li, cache)
    if attrs:
        _populate_from_attrs(li, attrs)
        if li.street_address:
            counts["fuzzy_partial_match"] += 1
            return

    counts["no_match"] += 1
