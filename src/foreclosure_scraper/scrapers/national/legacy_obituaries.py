"""Legacy.com obituary search -> probate lead cross-reference.

RE-ENABLED 2026-10-13 — real scoping mechanism found and live-verified.
Disabled 2026-09-15 (national.* zero-row audit) after the old URL params
(`term=`, `countryId=1`, `stateId={state.lower()}`, e.g. `stateId=nc`)
were confirmed to silently not scope anything: a search for "Asheville"
returned real obituaries from Tampa FL, New Britain CT, and New Zealand.

Root cause, found by driving legacy.com's actual search UI (not guessing):
NONE of `term`, `countryId`, `stateId`, `dateFrom` are params the backend
reads at all. Selecting filters through the real Location facet (Country ->
State -> City dropdowns) shows the page rewrite its own URL to
`?country=United+States&state=North+Carolina&city=Asheville` — i.e. the
real params are `country`, `state`, `city`, and all three take the
human-readable *full names* exactly as shown in the UI (not abbreviations,
not numeric IDs). Re-requesting the OLD broken params
(`term=Asheville&dateFrom=...&countryId=1&stateId=nc`) reproduces the exact
garbage-emitter bug (returned an Albany, NY obituary for an Asheville
search) -- confirming the old code was hitting an effectively-unfiltered
default feed on every single request, not a loosely-scoped one.

Live verification (2026-10-13, via curl impersonating a real browser UA,
i.e. no CAPTCHA/WAF bypass needed -- see http_client.get_text_impersonate):
all 19 `_CITIES` entries were fetched live with the corrected
`country=United+States&state=<full state name>&city=<city>` params. Every
one returned 50 real obituary rows (no empty/blocked responses). Manual
inspection of 100 rows across 2 cities (Asheville NC, Hendersonville NC)
found the fix overwhelmingly correct but NOT perfect: 1 of 100 inspected
rows was a genuine mis-scope (a Culpeper, VA obituary returned for a
Hendersonville, NC + North Carolina search) -- legacy.com's own city/state
facet has a small real leak rate, not zero. Because of that, `_fetch_city`
below adds a server-side verification pass per the original design intent
("verify results server-side before trusting them"): a row is kept and
tagged `verified=True` if its own text mentions the target city, the full
target state name, or a ", NC"/", SC"-style abbreviation; a row is DROPPED
outright if it explicitly names a *different* US state (full name) or New
Zealand/UK tells (same giveaways as the original bug) with no matching
signal for our own target state. Rows with no location cue at all in the
(short, site-truncated) preview text are kept but tagged `verified=False`
-- the project's existing downstream scope gate (cross-reference against
county property/owner records; see module history) is the final arbiter
for those, same safety net that made the old bug "currently harmless" per
the prior disabled-state docstring.

Original design intent, still true: Legacy.com aggregates obituaries from
1000s of funeral homes and newspapers -- a genuinely strong probate-lead
signal (deceased owner -> heirs likely to sell) now that the search can
actually be scoped.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
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

# Real param values legacy.com's Location facet sends (confirmed by driving
# the live UI -- see module docstring). Country is always this literal
# string for the US; state is the full name, not the 2-letter code.
_COUNTRY = "United States"
_STATE_FULL = {"NC": "North Carolina", "SC": "South Carolina"}

# Full names of every OTHER US state, used only to detect a row that
# explicitly names a different state than the one we searched for (a
# verified-real failure mode of legacy.com's own city/state facet -- see
# docstring). Deliberately full names only (not abbreviations): 2-letter
# codes like "OR"/"IN"/"ME"/"HI" collide with common English words and
# would false-positive constantly.
_OTHER_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
    "Rhode Island", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin",
    "Wyoming",
    # Same non-US giveaways the original bug surfaced.
    "New Zealand", "United Kingdom",
]

# Name pattern from obituary headlines: "John A. Smith" or "John Smith"
_NAME_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)", re.MULTILINE)
# Age pattern: "age 78" or "aged 78"
_AGE_RE = re.compile(r"\bage[d]?\s+(\d{1,3})\b", re.I)


def _scope_signal(text: str, city: str, state: str) -> tuple[bool, bool]:
    """Check a result's own text against the city/state we searched for.

    Returns (verified, contradicted):
      verified     -- text mentions the target city, the full target state
                       name, or a ", NC"/", SC"-style abbreviation.
      contradicted -- text explicitly names a DIFFERENT state (or the
                       New Zealand/UK tells from the original bug) with no
                       match for our own target state/city.
    """
    state_full = _STATE_FULL[state]
    own_hit = (
        city.lower() in text.lower()
        or state_full.lower() in text.lower()
        or re.search(rf",\s*{state}\b", text) is not None
    )
    if own_hit:
        return True, False
    other_hit = any(name in text for name in _OTHER_STATE_NAMES)
    return False, other_hit


class LegacyObituariesScraper(BaseScraper):
    slug = "national.legacy_obituaries"
    name = "Legacy.com Obituaries -> Probate Leads"
    category = "probate"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 300.0  # Multiple city searches
    disabled = False

    async def _fetch_city(self, city: str, state: str) -> list[Listing]:
        out: list[Listing] = []
        params = {"country": _COUNTRY, "state": _STATE_FULL[state], "city": city}
        url = f"{_SEARCH}?{urllib.parse.urlencode(params)}"

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

                verified, contradicted = _scope_signal(block, city, state)
                if contradicted:
                    continue

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
                            "search_params": params,
                            "verified": verified,
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

            verified, contradicted = _scope_signal(text, city, state)
            if contradicted:
                log.info("legacy.scope_reject", city=city, state=state, name=name,
                         text=text[:160])
                continue

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
                        "search_params": params,
                        "verified": verified,
                    },
                },
            ))

        log.info("legacy.city_done", city=city, state=state, count=len(out))
        return out

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for city, state in _CITIES:
            city_results = await self._fetch_city(city, state)
            out.extend(city_results)
            self.partial.extend(city_results)
        log.info("legacy.done", total=len(out), cities=len(_CITIES))
        return out
