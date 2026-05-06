"""Forsyth NC tax foreclosure sales — county Tax Department."""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing
from ._nc_tax_helper import fetch_county_tax_listings


URL = "https://www.co.forsyth.nc.us/tax/foreclosure_prop.aspx"


class ForsythTaxForeclosure(BaseScraper):
    slug = "counties_nc.forsyth_tax"
    name = "Forsyth NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 0
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await fetch_county_tax_listings(
            slug=self.slug, county="Forsyth", url=URL,
        )
