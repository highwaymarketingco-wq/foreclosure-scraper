"""Legacy.com obituary search -> probate lead cross-reference.

DISABLED 2026-09-15 (national.* zero-row audit) — confirmed garbage
emitter. The search URL passes `stateId={state.lower()}` (e.g.
`stateId=nc`) and `countryId=1`, but live-verified this silently does
NOT scope the results: a search for "Asheville" obituaries returned real
obituaries from Tampa FL, New Britain CT, and — via UK/NZ spelling
conventions in the text ("nee Matthews", "Whangarei Hospital") — New
Zealand. `stateId` almost certainly expects a numeric database ID on
legacy.com's real search backend, not a 2-letter state abbreviation, so
the filter is effectively a no-op; the scraper then tags EVERY result
`search_city`/`search_state` from the query regardless of the obituary's
actual location, producing 684 rows/run of fabricated-geography estate
leads. If `.obituary/.result/.listing-item/article` selectors ever come
back empty there's also a page-wide "scan for any Title-Case name"
fallback below, which carries the same risk this project has disabled
elsewhere (city_websites.search, seeclickfix). Currently harmless (every
row lacks county/zip and gets dropped at the scope gate) but disabled
outright rather than left dormant, same reasoning as those two.

Original design intent, for a future real rebuild: Legacy.com aggregates
obituaries from 1000s of funeral homes and newspapers — a genuinely
strong probate-lead signal (deceased owner -> heirs likely to sell) IF
the search can be scoped correctly. A real fix needs to find the actual
numeric stateId values legacy.com's search expects (or a lat/lng-radius
param instead), and verify results server-side before trusting them.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.legacy.com"
_SEARCH = f"{_BASE}/obituaries/search"

# Footprint cities for search.
_CITIES = [
    ("Asheville", "NC"), ("Hendersonville", "NC"), ("Brevard", "NC"),
    ("Rutherfordton", "NC"), ("Marion", "NC"), ("Shelby", "NC"),
    ("Gastonia", "NC"), ("Lincolnton", "NC"), ("Morganton", "NC"),
    ("Sylva", "NC"), ("Burnsville", "NC"), ("Forest City", "NC"),
    ("Spartanburg", "SC"), ("Gaffney", "SC"), ("Union", "SC"),
    ("Laurens", "SC"), ("Pickens", "SC"), ("Anderson", "SC"),
    ("Walhalla", "SC"),
]

# Name pattern from obituary headlines: "John A. Smith" or "John Smith"
_NAME_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)", re.MULTILINE)
# Age pattern: "age 78" or "aged 78"
_AGE_RE = re.compile(r"\bage[d]?\s+(\d{1,3})\b", re.I)


class LegacyObituariesScraper(BaseScraper):
    slug = "national.legacy_obituaries"
    name = "Legacy.com Obituaries -> Probate Leads"
    category = "probate"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 300.0  # Multiple city searches

    async def _fetch_city(self, city: str, state: str) -> list[Listing]:
        out: list[Listing] = []
        # Search for obituaries from the last 30 days.
        today = datetime.utcnow()
        date_from = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        url = f"{_SEARCH}/?term={city}&dateFrom={date_from}&countryId=1&stateId={(state.lower())}"

        try:
            html = await get_text_impersonate(url, timeout=45.0)
        except Exception as exc:
            log.warning("legacy.fetch_fail", city=city, error=str(exc)[:160])
            return []

        if not html or len(html) < 500:
            return []

        tree = HTMLParser(html)

        # Obituary listings are in div/article elements.
        entries = tree.css(".obituary, .result, .listing-item, article")
        if not entries:
            # Fallback: scan text for name patterns.
            body = tree.body.text(separator="\n") if tree.body else html
            for m in _NAME_RE.finditer(body):
                name = m.group(1).strip()
                if len(name) < 5:
                    continue
                # Skip common false positives.
                if name.lower() in ("funeral home", "memorial chapel"):
                    continue
                # Look for age in context.
                start = max(0, m.start() - 100)
                end = min(len(body), m.end() + 300)
                block = body[start:end]
                age = None
                am = _AGE_RE.search(block)
                if am:
                    try:
                        age = int(am.group(1))
                    except ValueError:
                        pass

                out.append(Listing(
                    source=self.slug,
                    source_url=url,
                    listing_type=ListingType.ESTATE_LEAD,
                    property_kind=PropertyKind.UNKNOWN,
                    owner_name=name,
                    city=city,
                    state=state,
                    county=None,
                    description=f"Obituary: {name} ({city}, {state})",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        "legacy": {
                            "deceased_name": name,
                            "age": age,
                            "obituary_excerpt": block[:500],
                            "search_city": city,
                            "search_state": state,
                        },
                    },
                ))
            return out

        for entry in entries:
            text = entry.text(separator=" ").strip()
            if not text or len(text) < 20:
                continue
            # Extract name from the entry.
            nm = _NAME_RE.search(text)
            if not nm:
                continue
            name = nm.group(1).strip()
            if name.lower() in ("funeral home", "memorial chapel", "legacy com"):
                continue
            # Extract age.
            age = None
            am = _AGE_RE.search(text)
            if am:
                try:
                    age = int(am.group(1))
                except ValueError:
                    pass
            # Extract detail link.
            link_el = entry.css_first("a[href]")
            detail_url = ""
            if link_el:
                href = link_el.attributes.get("href", "")
                if href:
                    detail_url = href if href.startswith("http") else f"{_BASE}{href}"

            out.append(Listing(
                source=self.slug,
                source_url=detail_url or url,
                listing_type=ListingType.ESTATE_LEAD,
                property_kind=PropertyKind.UNKNOWN,
                owner_name=name,
                city=city,
                state=state,
                county=None,
                description=f"Obituary: {name} ({city}, {state})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "legacy": {
                        "deceased_name": name,
                        "age": age,
                        "obituary_text": text[:500],
                        "detail_url": detail_url,
                        "search_city": city,
                        "search_state": state,
                    },
                },
            ))

        log.info("legacy.city_done", city=city, state=state, count=len(out))
        return out

    async def fetch(self) -> Iterable[Listing]:
        # Disabled — see module docstring. Confirmed garbage emitter (the
        # city/state search params don't actually scope the results).
        return []

    async def _disabled_fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for city, state in _CITIES:
            city_results = await self._fetch_city(city, state)
            out.extend(city_results)
        log.info("legacy.done", total=len(out), cities=len(_CITIES))
        return out
