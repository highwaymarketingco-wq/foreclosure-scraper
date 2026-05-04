"""publicnoticesc.com — currently blocked by Cloudflare even via Scrapling.

The SC Press Association's public-notice aggregator sits behind Cloudflare
challenge-response that defeats both direct httpx AND Scrapling's
StealthyFetcher (camoufox). Connection times out repeatedly during
Page.goto. Working around this would require:
  - Paid residential-proxy network (against user's no-spend rule)
  - A logged-in session with anti-bot bypass cookies
  - Cloudflare Solver service (paid)

Until a free path opens up, this scraper returns [] silently. SC public
notices are partially captured via:
  - counties_sc.sc_public_index_lis_pendens (state portal direct)
  - law_firms.* scrapers when SC trustee firms post their own
  - Mecklenburg/Anderson/Spartanburg masters-in-equity scrapers

Re-enable: when a free Cloudflare-bypass path opens up.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class PublicNoticeSC(BaseScraper):
    slug = "public_notices.publicnoticesc"
    name = "Public Notice SC (SCPA)"
    category = "public_notice"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        log.info("publicnoticesc.skipped",
                 reason="Cloudflare blocks Scrapling; SC notices partially covered elsewhere")
        return []
