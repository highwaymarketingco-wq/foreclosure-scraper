"""New Hanover NC tax foreclosure sales."""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing
from ._nc_tax_helper import fetch_county_tax_listings


URL = "https://tax.nhcgov.com/345/Foreclosures---Next-Auction-is-September"


class NewHanoverTaxForeclosure(BaseScraper):
    slug = "counties_nc.new_hanover_tax"
    name = "New Hanover NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 0
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await fetch_county_tax_listings(
            slug=self.slug, county="New Hanover", url=URL,
        )
