"""publicnoticesc.com — WALL STATUS CHANGED (re-verified live 2026-10-01).

HISTORICAL: this used to sit behind Cloudflare challenge-response that
defeated both direct httpx AND Scrapling's StealthyFetcher (camoufox).

RE-VERIFIED LIVE 2026-10-01 (HERMES sec 8 audit, per the "DEAD means dead
the day it was probed, not forever" rule): the Cloudflare wall is GONE. A
bare `curl` with no stealth/impersonation at all now gets a clean 200 and a
301 redirect to `https://www.scpublicnotices.com/(S(...))/default.aspx` --
the South Carolina Press Association's notice portal, now running on "LRS
Web Solutions" (the same vendor/platform family used by many state press
associations' public-notice sites nationwide).

NOT YET BUILT, because the search itself is a classic ASP.NET WebForms
postback UI (`Search.aspx`), not a simple GET query string or a JSON API:
results require a __VIEWSTATE/__EVENTVALIDATION token pair read from the
page, one or more county checkboxes (`lstCounty$N`, keyed by a numeric index
whose county mapping has to be read from the page's own labels, not
guessed) checked via `__doPostBack`, and a session cookie kept across the
GET-then-POST pair. That is a real, scoped, free, no-login, no-CAPTCHA build
(a multi-step httpx POST sequence, no browser required) -- just a
meaningfully bigger lift than a field/regex fix, so it was not attempted in
this audit pass. This scraper still returns [] until that is built.

SC public notices are partially captured in the meantime via:
  - counties_sc.sc_public_index_lis_pendens (state portal direct)
  - law_firms.* scrapers when SC trustee firms post their own
  - Mecklenburg/Anderson/Spartanburg masters-in-equity scrapers
  - counties.column_legal_notices (statewide SC "Foreclosure Sale" +
    "Estate (Probate) Filings" lanes, a different free source entirely)

Re-enable: build the ASP.NET postback sequence above against
`https://www.scpublicnotices.com/Search.aspx`.
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
        log.info(
            "publicnoticesc.not_built",
            reason=(
                "Cloudflare wall is GONE (re-verified 2026-10-01, plain 200 -> "
                "redirect to scpublicnotices.com); search itself is an "
                "un-built ASP.NET WebForms postback flow, not a quick fix. "
                "SC notices partially covered elsewhere in the meantime."
            ),
        )
        return []
