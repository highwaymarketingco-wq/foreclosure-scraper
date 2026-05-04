"""Zillow foreclosure listings — gracefully empty (no Apify, no spend).

Zillow blocks unauthenticated scraping aggressively (Cloudflare + behavioral
detection). Even Scrapling stealth typically gets challenged. Since we
already use Zillow zestimate enrichment elsewhere (per-address lookup which
DOES work) and HomeHarvest covers Realtor.com foreclosure inventory, this
mass-listing scraper is low marginal value relative to the engineering
required to keep it running.

Returns [] silently. To re-enable, build a Scrapling implementation that
handles Zillow's behavioral challenges.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class ZillowForeclosures(BaseScraper):
    slug = "national.zillow_foreclosures"
    name = "Zillow Foreclosures"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        log.info("zillow_foreclosures.skipped",
                 reason="aggressive anti-bot; per-address Zestimate enrichment used instead")
        return []
