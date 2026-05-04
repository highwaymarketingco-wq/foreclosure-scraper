"""Trulia foreclosure listings — gracefully empty (no Apify, no spend).

Trulia is a Zillow subsidiary and uses Zillow's aggressive anti-bot. Even
Scrapling stealth gets blocked or rate-limited. Since HomeHarvest already
covers Realtor.com and we have Zillow zestimate enrichment elsewhere, the
unique value of Trulia foreclosure listings is marginal.

This scraper is kept registered (so removing it doesn't break orchestrator
expectations) but returns [] silently. To re-enable, swap to a Scrapling
implementation similar to fannie_homepath.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class TruliaForeclosures(BaseScraper):
    slug = "national.trulia"
    name = "Trulia Foreclosures"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        log.info("trulia.skipped",
                 reason="zillow-grade anti-bot; HomeHarvest covers same data")
        return []
