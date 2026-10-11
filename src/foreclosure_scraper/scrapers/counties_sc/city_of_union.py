"""City of Union SC — JS "Client Challenge" bot shield.

cityofunion.net uses a JavaScript client challenge that requires a real
browser to evaluate JS and produce a valid session cookie.

Strategy: Use nodriver (undetected Chrome) to render the page, which
automatically evaluates the JS challenge and gets through. Then parse
the page content for property/foreclosure listings.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URLS = [
    "https://www.cityofunion.net/departments/finance/tax",
    "https://www.cityofunion.net/departments/building-codes",
    "https://www.cityofunion.net/news",
]


class CityOfUnionScraper(BaseScraper):
    """City of Union SC — JS Client Challenge via nodriver."""

    slug = "counties_sc.city_of_union"
    name = "City of Union SC"
    category = "municipal"
    timeout_s = 300.0

    async def _collect(self) -> list[Listing]:
        results: list[Listing] = []

        from ...wall_bypass import fetch_through_walls, fetch_with_nodriver

        for url in _URLS:
            try:
                log.info("city_of_union.fetching", url=url)

                html = await fetch_with_nodriver(url, timeout_s=45)

                if not html or len(html) < 500:
                    html = await fetch_through_walls(url, render_first=True)

                if not html or len(html) < 500:
                    log.warning("city_of_union.empty", url=url)
                    continue

                soup = BeautifulSoup(html, "html.parser")

                text = soup.get_text().lower()
                if any(kw in text for kw in [
                    "foreclosure", "tax sale", "delinquent", "condemned",
                    "surplus", "auction", "sheriff sale"
                ]):
                    addr_pattern = re.compile(
                        r"\b(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
                        r"(?:St|Street|Ave|Avenue|Blvd|Drive|Dr|Rd|Road|"
                        r"Lane|Ln|Way|Place|Pl|Ct|Court))\b"
                    )
                    page_text = soup.get_text()
                    for match in addr_pattern.finditer(page_text):
                        addr = match.group(1)
                        results.append(Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.UNKNOWN,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr,
                            city="Union",
                            county="Union",
                            state="SC",
                            raw={"extracted_from_text": True},
                        ))

                rows = soup.select("table tr")
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue
                    addr = cells[0].get_text(strip=True)
                    if addr and len(addr) > 5:
                        results.append(Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.UNKNOWN,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr,
                            city="Union",
                            county="Union",
                            state="SC",
                            raw={"from_table": True},
                        ))

                log.info("city_of_union.page_done", url=url, found=len(results))

            except Exception as exc:
                log.warning("city_of_union.page_error", url=url, error=str(exc)[:200])

        return results
