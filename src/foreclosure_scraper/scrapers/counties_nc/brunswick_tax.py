"""Brunswick County NC tax-foreclosure auctions.

Scope rollback added Brunswick to NC_COUNTIES on 2026-05-07c. The
county's tax-foreclosure activity is comparatively low (coastal,
small population), so weeks with zero listings are normal.

Per the Brunswick Tax Foreclosures page (verified 2026-05-07):
  * Auctions held at the Brunswick County Courthouse, Bolivia NC
  * Standard 10-day NCGS §45-21.27 upset bid window applies
  * Current sales are advertised on a Legal Notices subpage
    (/912/Legal-Notices) which loads dynamically via CivicPlus
  * No structured published roster (PDF / table) — content appears
    inline when sales are scheduled

Strategy: re-use the shared _nc_tax_helper which fetches with retry,
tries the legacy 5-column table parser first, then falls back to
the paragraph/regex parser tolerant of CivicPlus-style markup.
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing
from ._nc_tax_helper import fetch_county_tax_listings


URL = "https://www.brunswickcountync.gov/493/Tax-Foreclosures"


class BrunswickTaxForeclosure(BaseScraper):
    slug = "counties_nc.brunswick_tax"
    name = "Brunswick NC Tax Foreclosure Sales"
    category = "county_tax"
    # Brunswick has months with zero active sales — small coastal county.
    # expected_min_count=0 so dry weeks don't fire false REGRESSED alerts.
    expected_min_count = 0
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await fetch_county_tax_listings(
            slug=self.slug, county="Brunswick", url=URL,
        )
