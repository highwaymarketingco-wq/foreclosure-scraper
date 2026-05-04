"""Zillow bulk foreclosure search — gracefully empty (no Apify, no spend).

Same anti-bot constraints as zillow_foreclosures. Returns [] silently.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class ZillowBulk(BaseScraper):
    slug = "national.zillow_bulk"
    name = "Zillow Bulk Foreclosures"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        log.info("zillow_bulk.skipped",
                 reason="aggressive anti-bot; HomeHarvest covers Realtor instead")
        return []
