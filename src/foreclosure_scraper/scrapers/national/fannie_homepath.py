"""Fannie Mae HomePath REO — currently no working public scrape path.

Fannie HomePath has been restructured into a fully client-side React SPA
that requires authenticated session interactions to surface listings.
Direct URL hits (homepath.com/listing-search?state=NC etc.) redirect to
404 or render an empty shell with no listings, even via Scrapling stealth.

Fannie's real-time inventory IS reachable but only via:
  - Authenticated browser session with cookies
  - Real interaction with the city/state selector

Until we have a working path, this scraper returns [] silently. The
existing realtor_foreclosures (HomeHarvest) covers most Fannie REO listed
on Realtor.com anyway, so the marginal data loss is small.

Re-enable: when Fannie restores a public listing URL or we add an
authenticated browser session.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class FannieHomePath(BaseScraper):
    slug = "national.fannie_homepath"
    name = "Fannie Mae HomePath (REO)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        log.info("fannie_homepath.skipped",
                 reason="public listing URL dead post-restructure; HomeHarvest covers most Fannie listings")
        return []
