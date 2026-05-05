"""Durham NC tax foreclosure sales — county Tax Administration."""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing
from ._nc_tax_helper import fetch_county_tax_listings


URL = "https://dconc.gov/Tax-Administration/Payment-Options-and-Collections/Foreclosure"


class DurhamTaxForeclosure(BaseScraper):
    slug = "counties_nc.durham_tax"
    name = "Durham NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 0
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await fetch_county_tax_listings(
            slug=self.slug, county="Durham", url=URL,
        )
