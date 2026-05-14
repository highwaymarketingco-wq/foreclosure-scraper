"""Hubzu — React SPA with anti-bot, listings unreachable via Scrapling.

Hubzu's `/properties` and `/property-search/state/{ST}` URLs serve only
an empty React app shell — listings load via an internal authenticated
API after JS execution. Scrapling stealth renders the shell but the API
calls never fire (CDN fingerprint check rejects headless), and pushing
past it via prolonged page interaction triggers a Chrome target crash.

Until a session-cookie-bearing direct API call is reverse-engineered,
this scraper short-circuits to [] in ~1s rather than wasting 60-120s on
a Scrapling render that yields no data.

To re-enable: open Hubzu in a real browser, capture the listings XHR
that fires after login or session setup, and replay it via httpx with
the right Cookie/Authorization header set.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class Hubzu(BaseScraper):
    slug = "national.hubzu"
    name = "Hubzu (REO Auction — SPA-blocked)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    requires_render = True
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        log.info(
            "hubzu.skipped",
            reason=(
                "React SPA; listings load via internal API that doesn't fire "
                "under Scrapling. Reverse-engineer the authenticated XHR + "
                "replay via httpx to enable."
            ),
        )
        return []
