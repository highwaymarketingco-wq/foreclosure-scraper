"""VRM Properties — VA REO listings (federal source).

VRM Properties is the prime contractor managing VA-foreclosed properties
nationwide. Their public search at https://vrmproperties.com/ exposes
listings with state filter; auth not required for browsing.

Volume is small per state but the listings are vet-foreclosure REO,
which often haven't yet hit MLS.

Note: the search page is JS-rendered (React SPA). Plain httpx returns
the app shell only. This scraper short-circuits to [] until a Scrapling
stealth flow lands; classified ``requires_render=True`` so the run
summary shows RENDER-REQUIRED rather than REGRESSED.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


URL = "https://vrmproperties.com/"


class VRMPropertiesVAREO(BaseScraper):
    slug = "reo.vrm_va_reo"
    name = "VRM Properties — VA REO (paywalled UI)"
    category = "federal_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = True   # JS-rendered React SPA
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        log.info(
            "vrm_va_reo.skeleton",
            note=(
                "VRM is a JS-rendered React SPA; plain httpx returns the app "
                "shell. Drop in a Scrapling page_action that waits for "
                "the listings table, paginates by state, and parses the "
                "rendered HTML to start producing listings."
            ),
        )
        return []
