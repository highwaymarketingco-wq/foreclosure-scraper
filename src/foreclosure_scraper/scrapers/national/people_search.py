"""People-search sites — TruePeopleSearch, FastPeopleSearch.

truepeoplesearch.com and fastpeoplesearch.com are behind Cloudflare.
They provide free people search (name, address, phone) which is useful
for enriching owner/defendant names with contact info.

Strategy: Use wall_bypass escalation (curl-cffi → pydoll → nodriver)
to get past Cloudflare, then search by name and parse results.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_SITES = {
    "truepeoplesearch": {
        "url": "https://www.truepeoplesearch.com",
        "search_path": "/results?name=",
    },
    "fastpeoplesearch": {
        "url": "https://www.fastpeoplesearch.com",
        "search_path": "/name/",
    },
}

# Sample of names to search — in production, these would come from the
# board's defendant/owner names. For now, search a small sample.
_SAMPLE_NAMES = [
    "John Smith", "Robert Johnson", "Mary Davis",
]


class PeopleSearchScraper(BaseScraper):
    """People-search sites via wall_bypass."""

    slug = "national.people_search"
    name = "People Search Sites"
    category = "people_search"
    timeout_s = 300.0

    async def _collect(self) -> list[Listing]:
        results: list[Listing] = []

        for site_name, cfg in _SITES.items():
            for name in _SAMPLE_NAMES:
                try:
                    search_url = f"{cfg['url']}{cfg['search_path']}" \
                                 f"{name.replace(' ', '+')}"
                    log.info("people_search.fetching",
                             site=site_name, name=name)

                    html = await client.get_text(
                        search_url,
                        wall_bypass=True,
                        timeout=30.0,
                    )

                    if not html or len(html) < 500:
                        from ...wall_bypass import fetch_with_nodriver
                        html = await fetch_with_nodriver(search_url, timeout_s=45)

                    if not html or len(html) < 500:
                        log.warning("people_search.empty",
                                    site=site_name, name=name)
                        continue

                    soup = BeautifulSoup(html, "html.parser")

                    # Parse people search results
                    cards = soup.select(
                        ".card, .result-card, .person-card, "
                        ".search-result, .listing"
                    )

                    for card in cards:
                        text = card.get_text(separator=" | ", strip=True)
                        # Extract address
                        addr_match = re.search(
                            r"(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
                            r"(?:St|Street|Ave|Avenue|Blvd|Dr|Rd|Road|"
                            r"Lane|Ln|Way|Pl|Ct))",
                            text
                        )
                        # Extract age
                        age_match = re.search(r"Age\s*(\d+)", text, re.I)

                        results.append(Listing(
                            source=self.slug,
                            source_url=cfg["url"],
                            listing_type=ListingType.UNKNOWN,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr_match.group(1) if addr_match else "",
                            owner_name=name,
                            raw={
                                "site": site_name,
                                "full_text": text[:500],
                                "age": age_match.group(1) if age_match else None,
                            },
                        ))

                    log.info("people_search.name_done",
                             site=site_name, name=name,
                             found=len(results))

                except Exception as exc:
                    log.warning("people_search.search_error",
                                site=site_name, name=name,
                                error=str(exc)[:200])

        return results
