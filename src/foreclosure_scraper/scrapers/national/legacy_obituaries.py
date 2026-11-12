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
all 19 original `_CITIES` entries were fetched live with the corrected
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

RAW-SHAPE FIX + COUNTY EXPANSION (2026-11-11). Two bugs found checking why
`atty_obituary_match` ("no source known", 113 NC+SC counties per
docs/gap_matrix) didn't credit this scraper despite it being enabled, wired
into main.py, and live-verified above:

  1. Every row here was hand-built with `raw={"legacy": {...}}` and
     `listing_type=ESTATE_LEAD`. The column's own check
     (`gap_matrix.obituary_matched`) and every sibling obituary reader
     (gannett_obituaries.py, funeral_home_rss.py, obituary_feeds.py,
     echovita_obituaries.py) instead key off `raw["obituary"]` (a dict) and
     `life_event == "death"` -- the shared `obituary_listing()` factory in
     `scrapers/public_notices/_obit_common.py`. This scraper never called
     it, so its real, live rows were invisible to the signal they exist to
     produce. Fixed by building every row through that same shared
     factory (also gets free survivor parsing + the private/public split
     the other readers already have).
  2. `_CITIES` carried `county=None` for every row (by design, deferred to
     later name->property enrichment -- see the matching comment in
     main.py next to this slug's registration). Since each of the 19
     original cities (and the ones added below) is chosen specifically
     *because* it sits in one known county, the county is attached
     directly now via `CITY_COUNTY` -- strictly safer than the deferred
     path, not a new risk, and it is what makes `atty_obituary_match`
     county-scoped credit actually land.

Cross-checking the 19 original cities against the 113-county gap list
found 11 counties legacy.com was *already covering live* the whole time,
just never credited (Burke, Jackson, Lincoln, McDowell, Transylvania,
Yancey NC; Cherokee, Laurens, Oconee, Pickens, Union SC) -- fix (1) alone
closes those with zero new scraping. The other 102 gap counties are new:
one representative city per county, taken from this repo's own existing,
already-reviewed `_bankruptcy_city_to_county.py` / `_coastal_city_to_county.py`
/ `_upstate_city_to_county.py` crosswalks (not hand-typed, and every county
name checked programmatically against `validation.NC_COUNTIES`/
`SC_COUNTIES`), same `country`/`state`/`city` request shape proven above.

HONEST STATUS on the 102 new cities specifically: a bounded live spot-check
of 7 of them (2026-11-11, 2 attempts ~45s apart) got HTTP 429 from
legacy.com both times -- this Mac's IP was rate-limited at test time
(plausibly from the regular pipeline's own run against the original 19
cities earlier that same day/night; a 429 is the same "throttling our
volume, not a wall" shape gannett_obituaries.py's own docstring documents,
not a structural block). The request shape itself is unchanged from the
19-city version verified live 2026-10-13 and run for real 2026-09-08 (665
rows across those 19 cities, see logs/*.log "legacy.done"). This scraper's
own per-city error handling (one failed/empty city does not drop the
others, see tests) makes a bad new-city guess harmless; real per-county
yield for the 102 will show up in this scraper's own `legacy.city_done` /
`legacy.done` log lines on its next scheduled run. Also added a 2.0s
inter-city pacing gap (matching this project's established
`_obit_common.PoliteFetcher.MIN_GAP_S` convention, absent here before) and
raised `timeout_s` accordingly, since 121 cities back-to-back with no gap
is a materially different request pattern than the original 19 and more
likely to draw exactly this kind of rate limiting.

Original design intent, still true: Legacy.com aggregates obituaries from
1000s of funeral homes and newspapers -- a genuinely strong probate-lead
signal (deceased owner -> heirs likely to sell) now that the search can
actually be scoped.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text_impersonate
from ...models import Listing
from ..public_notices._obit_common import obituary_listing

log = structlog.get_logger()

_BASE = "https://www.legacy.com"
_SEARCH = f"{_BASE}/obituaries/search"

# Inter-request pacing to legacy.com (one host, all cities) -- matches this
# project's established obituary-reader convention
# (_obit_common.PoliteFetcher.MIN_GAP_S) rather than hammering 121 cities
# back-to-back.
_GAP_S = 2.0

# city/state -> county. Every value here is checked against
# validation.NC_COUNTIES/SC_COUNTIES (see module docstring, 2026-11-11 fix).
# The first 19 are the original WNC + Upstate-SC core footprint; the rest
# are the 102 still-genuinely-uncovered counties of the 113-county
# atty_obituary_match gap (the other 11 of that 113 turned out to already
# be among the original 19 -- see docstring).
CITY_COUNTY: dict[tuple[str, str], str] = {
    ("Asheville", "NC"): "Buncombe",
    ("Hendersonville", "NC"): "Henderson",
    ("Brevard", "NC"): "Transylvania",
    ("Rutherfordton", "NC"): "Rutherford",
    ("Marion", "NC"): "McDowell",
    ("Shelby", "NC"): "Cleveland",
    ("Gastonia", "NC"): "Gaston",
    ("Lincolnton", "NC"): "Lincoln",
    ("Morganton", "NC"): "Burke",
    ("Sylva", "NC"): "Jackson",
    ("Burnsville", "NC"): "Yancey",
    ("Forest City", "NC"): "Rutherford",
    ("Spartanburg", "SC"): "Spartanburg",
    ("Gaffney", "SC"): "Cherokee",
    ("Union", "SC"): "Union",
    ("Laurens", "SC"): "Laurens",
    ("Pickens", "SC"): "Pickens",
    ("Anderson", "SC"): "Anderson",
    ("Walhalla", "SC"): "Oconee",
    # -- 102 net-new counties (2026-11-11), one representative city each,
    # taken from this repo's own city->county crosswalks --
    ("Graham", "NC"): "Alamance",
    ("Taylorsville", "NC"): "Alexander",
    ("Sparta", "NC"): "Alleghany",
    ("Wadesboro", "NC"): "Anson",
    ("Jefferson", "NC"): "Ashe",
    ("Newland", "NC"): "Avery",
    ("Washington", "NC"): "Beaufort",
    ("Windsor", "NC"): "Bertie",
    ("Elizabethtown", "NC"): "Bladen",
    ("Bolivia", "NC"): "Brunswick",
    ("Lenoir", "NC"): "Caldwell",
    ("Camden", "NC"): "Camden",
    ("Beaufort", "NC"): "Carteret",
    ("Yanceyville", "NC"): "Caswell",
    ("Newton", "NC"): "Catawba",
    ("Pittsboro", "NC"): "Chatham",
    ("Murphy", "NC"): "Cherokee",
    ("Edenton", "NC"): "Chowan",
    ("Hayesville", "NC"): "Clay",
    ("Whiteville", "NC"): "Columbus",
    ("New Bern", "NC"): "Craven",
    ("Currituck", "NC"): "Currituck",
    ("Manteo", "NC"): "Dare",
    ("Lexington", "NC"): "Davidson",
    ("Mocksville", "NC"): "Davie",
    ("Kenansville", "NC"): "Duplin",
    ("Louisburg", "NC"): "Franklin",
    ("Gatesville", "NC"): "Gates",
    ("Robbinsville", "NC"): "Graham",
    ("Oxford", "NC"): "Granville",
    ("Snow Hill", "NC"): "Greene",
    ("Halifax", "NC"): "Halifax",
    ("Lillington", "NC"): "Harnett",
    ("Waynesville", "NC"): "Haywood",
    ("Winton", "NC"): "Hertford",
    ("Raeford", "NC"): "Hoke",
    ("Swan Quarter", "NC"): "Hyde",
    ("Trenton", "NC"): "Jones",
    ("Sanford", "NC"): "Lee",
    ("Kinston", "NC"): "Lenoir",
    ("Franklin", "NC"): "Macon",
    ("Marshall", "NC"): "Madison",
    ("Williamston", "NC"): "Martin",
    ("Bakersville", "NC"): "Mitchell",
    ("Troy", "NC"): "Montgomery",
    ("Carthage", "NC"): "Moore",
    ("Nashville", "NC"): "Nash",
    ("Jackson", "NC"): "Northampton",
    ("Jacksonville", "NC"): "Onslow",
    ("Hillsborough", "NC"): "Orange",
    ("Bayboro", "NC"): "Pamlico",
    ("Elizabeth City", "NC"): "Pasquotank",
    ("Burgaw", "NC"): "Pender",
    ("Hertford", "NC"): "Perquimans",
    ("Roxboro", "NC"): "Person",
    ("Columbus", "NC"): "Polk",
    ("Asheboro", "NC"): "Randolph",
    ("Rockingham", "NC"): "Richmond",
    ("Lumberton", "NC"): "Robeson",
    ("Wentworth", "NC"): "Rockingham",
    ("Salisbury", "NC"): "Rowan",
    ("Clinton", "NC"): "Sampson",
    ("Laurinburg", "NC"): "Scotland",
    ("Albemarle", "NC"): "Stanly",
    ("Danbury", "NC"): "Stokes",
    ("Dobson", "NC"): "Surry",
    ("Bryson City", "NC"): "Swain",
    ("Columbia", "NC"): "Tyrrell",
    ("Monroe", "NC"): "Union",
    ("Henderson", "NC"): "Vance",
    ("Warrenton", "NC"): "Warren",
    ("Plymouth", "NC"): "Washington",
    ("Boone", "NC"): "Watauga",
    ("Goldsboro", "NC"): "Wayne",
    ("Wilkesboro", "NC"): "Wilkes",
    ("Yadkinville", "NC"): "Yadkin",
    ("Aiken", "SC"): "Aiken",
    ("Allendale", "SC"): "Allendale",
    ("Bamberg", "SC"): "Bamberg",
    ("Beaufort", "SC"): "Beaufort",
    ("St Matthews", "SC"): "Calhoun",
    ("Chester", "SC"): "Chester",
    ("Chesterfield", "SC"): "Chesterfield",
    ("Walterboro", "SC"): "Colleton",
    ("Darlington", "SC"): "Darlington",
    ("Dillon", "SC"): "Dillon",
    ("St George", "SC"): "Dorchester",
    ("Winnsboro", "SC"): "Fairfield",
    ("Georgetown", "SC"): "Georgetown",
    ("Greenwood", "SC"): "Greenwood",
    ("Hampton", "SC"): "Hampton",
    ("Ridgeland", "SC"): "Jasper",
    ("Camden", "SC"): "Kershaw",
    ("Lancaster", "SC"): "Lancaster",
    ("Bishopville", "SC"): "Lee",
    ("Marion", "SC"): "Marion",
    ("Bennettsville", "SC"): "Marlboro",
    ("McCormick", "SC"): "McCormick",
    ("Newberry", "SC"): "Newberry",
    ("Saluda", "SC"): "Saluda",
    ("Sumter", "SC"): "Sumter",
    ("York", "SC"): "York",
}

# Footprint cities for search -- single source of truth is CITY_COUNTY above.
_CITIES: tuple[tuple[str, str], ...] = tuple(CITY_COUNTY.keys())

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
    timeout_s = 1200.0  # 121 cities at 2.0s pacing + request latency
    disabled = False

    async def _fetch_city(self, city: str, state: str) -> list[Listing]:
        out: list[Listing] = []
        county = CITY_COUNTY.get((city, state))
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

        def _make(name: str, age: int | None, text: str, detail_url: str,
                  verified: bool) -> Listing:
            return obituary_listing(
                source="national.legacy_obituaries", url=detail_url or url,
                decedent=name, state=state, county=county, publisher="Legacy.com",
                text=text, residence_city=city if verified else None, age=age,
                extra_public={"search_city": city, "search_state": state,
                              "verified": verified},
            )

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

                out.append(_make(name, age, block, "", verified))
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

            out.append(_make(name, age, text, detail_url, verified))

        log.info("legacy.city_done", city=city, state=state, county=county, count=len(out))
        return out

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for i, (city, state) in enumerate(_CITIES):
            if i:
                await asyncio.sleep(_GAP_S)
            city_results = await self._fetch_city(city, state)
            out.extend(city_results)
            self.partial.extend(city_results)
        log.info("legacy.done", total=len(out), cities=len(_CITIES))
        return out
