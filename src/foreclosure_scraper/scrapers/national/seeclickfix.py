"""SeeClickFix municipal issue API v2 — free, keyless bulk data.

FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 18) -- was
DISABLED 2026-09-15 (national.* zero-row audit) as a confirmed garbage
emitter: SeeClickFix's v2 API silently ignores the `lat`/`lng`/`radius`
geo-filter params (re-confirmed STILL true live 2026-10-04: a query for
Asheville NC's coordinates still returns issues from Mesquite TX, Cape
Winelands ZAF, Toledo OH, Oakland CA, Fort Lauderdale FL, Albuquerque NM,
Rock Island IL), and the old `_fetch_city` then HARDCODED
`city=c["city"], state=c["state"]` from the query dict rather than the
real returned address, fabricating geography on every row.

The real, free fix: SCF has a SEPARATE, genuinely-working `place_url`
scoping param (undocumented in the module's old note) -- confirmed live
2026-10-04 that `/api/v2/issues?place_url=<slug>` returns correctly
geo-scoped results, e.g. `place_url=spartanburg` -> 415 entries, all real
Spartanburg SC addresses. The slug is NOT always just the lowercased city
name though -- SCF's own `/api/v2/places?lat=&lng=` lookup (which DOES
state-disambiguate) caught a real collision: `place_url=hendersonville`
resolves to Hendersonville, TENNESSEE (wrong state entirely), while the
correct NC slug is `hendersonville_nc`. Every one of this module's 20
footprint cities was re-resolved this way (places-lookup first, verified
state match; a couple of slugs like `greer`/`union_3`/`anderson_3` needed
cross-checking directly against `/issues?place_url=` since the places
lookup's own nearest-point search didn't always surface the right City
object) and spot-checked against real live addresses before being hard-
coded below. A handful (Brevard/Rutherfordton/Marion/Sylva/Burnsville/
Union/Pickens/Walhalla) resolve to a real, state-verified SCF place that
currently has ZERO total issues ever reported -- plausible for small rural
towns, not a mapping error (the place_url itself is state-confirmed).

Issues tagged "code violation"/"abandoned property"/"blight"/"vacant"/
"graffiti" are real motivated-seller distress signals. API docs:
https://developer.seeclickfix.com/ — free, no key needed for basic
queries (rate-limited ~100 req/min).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_API = "https://seeclickfix.com/api/v2/issues"

# Footprint city -> real, state-verified SCF `place_url` slug (see module
# docstring's 2026-10-04 FOUND note for how each was resolved/verified).
# `county` is hardcoded from this project's own gazetteers
# (_upstate_city_to_county.upstate_county_for), not derived from the API,
# since these are the anchor cities WE chose, not something SCF returns.
_CITIES = [
    # NC
    {"city": "Asheville", "state": "NC", "county": "Buncombe", "place_url": "asheville"},
    {"city": "Hendersonville", "state": "NC", "county": "Henderson", "place_url": "hendersonville_nc"},
    {"city": "Brevard", "state": "NC", "county": "Transylvania", "place_url": "brevard"},
    {"city": "Rutherfordton", "state": "NC", "county": "Rutherford", "place_url": "rutherfordton"},
    {"city": "Marion", "state": "NC", "county": "McDowell", "place_url": "marion_10"},
    {"city": "Shelby", "state": "NC", "county": "Cleveland", "place_url": "shelby-nc"},
    {"city": "Gastonia", "state": "NC", "county": "Gaston", "place_url": "gastonia"},
    {"city": "Lincolnton", "state": "NC", "county": "Lincoln", "place_url": "lincolnton"},
    {"city": "Morganton", "state": "NC", "county": "Burke", "place_url": "morganton"},
    {"city": "Sylva", "state": "NC", "county": "Jackson", "place_url": "sylva"},
    {"city": "Burnsville", "state": "NC", "county": "Yancey", "place_url": "burnsville_3"},
    {"city": "Forest City", "state": "NC", "county": "Rutherford", "place_url": "forest-city"},
    # SC
    {"city": "Spartanburg", "state": "SC", "county": "Spartanburg", "place_url": "spartanburg"},
    {"city": "Greer", "state": "SC", "county": "Spartanburg", "place_url": "greer"},
    {"city": "Gaffney", "state": "SC", "county": "Cherokee", "place_url": "gaffney"},
    {"city": "Union", "state": "SC", "county": "Union", "place_url": "union_3"},
    {"city": "Laurens", "state": "SC", "county": "Laurens", "place_url": "laurens"},
    {"city": "Pickens", "state": "SC", "county": "Pickens", "place_url": "pickens"},
    {"city": "Anderson", "state": "SC", "county": "Anderson", "place_url": "anderson_3"},
    {"city": "Walhalla", "state": "SC", "county": "Oconee", "place_url": "walhalla"},
]

# Defense-in-depth sanity check: if an issue's own free-text address names a
# DIFFERENT, unexpected state outright, drop it rather than trust the
# place_url tag blindly -- live-verified 2026-10-04 that `place_url=shelby-nc`
# returned one row address-texted "Brownsville, TX" mixed into 20 otherwise-
# correct Shelby, NC rows (SCF's own place-tagging has occasional noise).
# A short allowlist of state tokens that must NOT appear (home state is
# deliberately not required to appear, since many real addresses are
# terse -- "281 Wells Drforest City NC 28043" -- and a strict require-state
# check would reject genuinely-good rows).
_OTHER_STATE_TOKENS = (
    "TX", "TN", "GA", "VA", "FL", "CA", "OH", "NM", "IL", "WA", "MI", "MA",
)


def _address_names_wrong_state(addr: str, expected_state: str) -> bool:
    if not addr:
        return False
    for tok in _OTHER_STATE_TOKENS:
        if tok == expected_state:
            continue
        if f", {tok}" in addr or f" {tok}," in addr or addr.strip().endswith(f" {tok}"):
            return True
    return False

# Issue categories / keywords that signal property distress.
_DISTRESS_KEYWORDS = (
    "blight", "vacant", "abandoned", "code violation", "condemn",
    "derelict", "dilapidated", "overgrown", "trash", "illegal dumping",
    "nuisance", "unsafe structure", "condemned",
)

_PER_PAGE = 100
_MAX_PAGES = 5  # 500 issues per city max


class SeeClickFixScraper(BaseScraper):
    slug = "national.seeclickfix"
    name = "SeeClickFix Municipal Issues (distress signals)"
    category = "municipal_distress"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 240.0
    # RE-ENABLED 2026-10-04 (HERMES extraction-completeness audit, batch 18)
    # -- see module docstring's FOUND note. Was DISABLED 2026-09-15 for the
    # lat/lng/radius bug; that bug is fixed (place_url scoping replaces it
    # entirely), so this is a real source again, not a dormant one.

    async def _fetch_city(self, c: dict) -> list[Listing]:
        out: list[Listing] = []
        async with client(timeout=30.0) as c_http:
            for page in range(1, _MAX_PAGES + 1):
                params = {
                    "place_url": c["place_url"],
                    "page": str(page),
                    "per_page": str(_PER_PAGE),
                    "sort": "updated_at",
                }
                try:
                    r = await c_http.get(_API, params=params)
                except Exception as exc:
                    log.warning("seeclickfix.fetch_fail", city=c["city"], page=page, error=str(exc)[:160])
                    break
                if r.status_code != 200:
                    log.warning("seeclickfix.status", city=c["city"], page=page, status=r.status_code)
                    break
                try:
                    data = r.json()
                except Exception:
                    log.warning("seeclickfix.json_fail", city=c["city"], page=page)
                    break
                issues = data.get("issues") or []
                if not issues:
                    break
                for iss in issues:
                    # Filter to distress-relevant categories.
                    summary = (iss.get("summary") or "").lower()
                    description = (iss.get("description") or "").lower()
                    combined = f"{summary} {description}"
                    if not any(kw in combined for kw in _DISTRESS_KEYWORDS):
                        continue
                    # Extract address if present.
                    addr = iss.get("address") or ""
                    # Defense-in-depth (see module docstring): SCF's own
                    # place-tagging occasionally mislabels a row from a
                    # different state (live-verified on shelby-nc). Drop it
                    # rather than silently fabricate geography again.
                    if _address_names_wrong_state(addr, c["state"]):
                        log.warning("seeclickfix.wrong_state_dropped", city=c["city"],
                                    expected_state=c["state"], address=addr[:120])
                        continue
                    lat = iss.get("lat")
                    lng = iss.get("lng")
                    issue_url = iss.get("html_url") or iss.get("url") or ""
                    out.append(Listing(
                        source=self.slug,
                        source_url=issue_url or _API,
                        listing_type=ListingType.DISTRESSED,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr or None,
                        city=c["city"],
                        state=c["state"],
                        # FOUND 2026-10-04 (batch 18): county is now a
                        # curated, gazetteer-verified value (see _CITIES),
                        # not the hardcoded None the disabled version
                        # shipped -- real rows can now actually clear the
                        # scope gate instead of being dropped unconditionally.
                        county=c["county"],
                        description=f"SeeClickFix: {iss.get('summary', '')[:200]}",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={
                            "seeclickfix": {
                                "issue_id": iss.get("id"),
                                "status": iss.get("status"),
                                "category": iss.get("category"),
                                "summary": iss.get("summary"),
                                "description": (iss.get("description") or "")[:500],
                                "lat": lat,
                                "lng": lng,
                                "created_at": iss.get("created_at"),
                                "updated_at": iss.get("updated_at"),
                                # No "reporter" (2026-10-08): SeeClickFix's reporter block is the
                                # private resident who filed the complaint (name, avatar), not the
                                # property owner; the public board never carries a complainant.
                                "url": issue_url,
                                "place_url": c["place_url"],
                            },
                        },
                    ))
                # Check if there are more pages.
                if len(issues) < _PER_PAGE:
                    break
        log.info("seeclickfix.city_done", city=c["city"], count=len(out))
        return out

    async def fetch(self) -> Iterable[Listing]:
        tasks = [self._fetch_city(c) for c in _CITIES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[Listing] = []
        for r in results:
            if isinstance(r, list):
                out.extend(r)
            else:
                log.warning("seeclickfix.city_error", error=str(r)[:160])
        log.info("seeclickfix.done", total=len(out), cities=len(_CITIES))
        return out
