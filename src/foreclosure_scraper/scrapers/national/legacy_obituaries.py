"""Legacy.com obituary search -> probate lead cross-reference.

Legacy.com aggregates obituaries from 1000s of funeral homes and newspapers.
We search for recent obituaries in our NC/SC footprint, then the enrichment
pipeline cross-references deceased names against property tax records to find
probate leads (deceased owner -> heirs likely to sell).

This scraper produces ESTATE_LEAD type listings when it finds an obituary
mentioning a city in our footprint. The enrichment pipeline (enrichment_probate)
then matches the deceased name against county tax records.

Free, public. Server-rendered HTML. Cloudflare-protected, so we use
impersonation for the TLS fingerprint.
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
        out: list[Listing] = []
        for city, state in _CITIES:
            city_results = await self._fetch_city(city, state)
            out.extend(city_results)
        log.info("legacy.done", total=len(out), cities=len(_CITIES))
        return out
