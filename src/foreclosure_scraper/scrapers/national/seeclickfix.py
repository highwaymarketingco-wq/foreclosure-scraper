"""SeeClickFix municipal issue API v2 — free, keyless bulk data.

SeeClickFix is a citizen-reporting platform used by 100s of US municipalities.
Issues tagged with categories like "code violation", "abandoned property",
"blight", "vacant", or "graffiti" are strong distress signals. The API is
free and requires no key for basic queries (rate-limited ~100 req/min).

API docs: https://developer.seeclickfix.com/
Endpoint: https://seeclickfix.com/api/v2/issues

We query for issues in our NC/SC footprint cities with distress-related
keywords, paginating through results. Each issue becomes a Listing with
listing_type=DISTRESS_SIGNAL (not a foreclosure per se, but a motivated-
seller indicator for properties with active municipal complaints).
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

# Footprint city -> {lat, lng, radius} for the API search. SeeClickFix
# uses lat/lng + radius (meters) bounding. We cover the core 18-county
# metro areas. 5000m radius covers most city cores.
_CITIES = [
    # NC
    {"city": "Asheville", "state": "NC", "lat": 35.5951, "lng": -82.5515, "radius": 8000},
    {"city": "Hendersonville", "state": "NC", "lat": 35.3185, "lng": -82.4600, "radius": 5000},
    {"city": "Brevard", "state": "NC", "lat": 35.2335, "lng": -82.7340, "radius": 5000},
    {"city": "Rutherfordton", "state": "NC", "lat": 35.3668, "lng": -81.9570, "radius": 5000},
    {"city": "Marion", "state": "NC", "lat": 35.6840, "lng": -82.0119, "radius": 5000},
    {"city": "Shelby", "state": "NC", "lat": 35.2923, "lng": -81.5346, "radius": 5000},
    {"city": "Gastonia", "state": "NC", "lat": 35.2621, "lng": -81.1873, "radius": 8000},
    {"city": "Lincolnton", "state": "NC", "lat": 35.4740, "lng": -81.2523, "radius": 5000},
    {"city": "Morganton", "state": "NC", "lat": 35.7454, "lng": -81.6848, "radius": 5000},
    {"city": "Sylva", "state": "NC", "lat": 35.3738, "lng": -83.2182, "radius": 5000},
    {"city": "Burnsville", "state": "NC", "lat": 35.9171, "lng": -82.2990, "radius": 5000},
    {"city": "Forest City", "state": "NC", "lat": 35.3343, "lng": -81.8637, "radius": 5000},
    # SC
    {"city": "Spartanburg", "state": "SC", "lat": 34.9496, "lng": -81.9320, "radius": 8000},
    {"city": "Greer", "state": "SC", "lat": 34.6157, "lng": -82.2271, "radius": 5000},
    {"city": "Gaffney", "state": "SC", "lat": 35.0718, "lng": -81.6498, "radius": 5000},
    {"city": "Union", "state": "SC", "lat": 34.6249, "lng": -81.6251, "radius": 5000},
    {"city": "Laurens", "state": "SC", "lat": 34.4990, "lng": -82.0184, "radius": 5000},
    {"city": "Pickens", "state": "SC", "lat": 34.8812, "lng": -82.7068, "radius": 5000},
    {"city": "Anderson", "state": "SC", "lat": 34.5034, "lng": -82.6501, "radius": 8000},
    {"city": "Walhalla", "state": "SC", "lat": 34.7632, "lng": -83.0646, "radius": 5000},
]

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

    async def _fetch_city(self, c: dict) -> list[Listing]:
        out: list[Listing] = []
        async with client(timeout=30.0) as c_http:
            for page in range(1, _MAX_PAGES + 1):
                params = {
                    "lat": str(c["lat"]),
                    "lng": str(c["lng"]),
                    "radius": str(c["radius"]),
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
                        county=None,
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
                                "reporter": iss.get("reporter"),
                                "url": issue_url,
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
