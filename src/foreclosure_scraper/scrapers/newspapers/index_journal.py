"""Index-Journal (Greenwood, SC) — foreclosure legal notices.

Greenwood County's daily legal-organ paper. Greenwood had NO dedicated newspaper/
notice scraper before this (the SCPA statewide site is WAF-blocked for us), so the
paper's own TownNews (TNCMS) legal-classifieds RSS is an independent, reachable path
that fills the county. The feed carries Master-in-Equity / Court of Common Pleas
foreclosure NOTICE OF SALE + mortgage-foreclosure SUMMONS and Greenwood County
Forfeited Land Commission (tax-sale) Invitation-to-Bid notices — full text in each
<item> description.

Verified live (2026-06-27): the feed returned a NOTICE OF SALE (C/A 2025CP2400887,
U.S. Bank Trust NA), a CP summons, and a Greenwood FLC invitation-to-bid. SC sale
addresses are resolved downstream by the case-number / owner-to-GIS enrichers.
Free, no login/WAF/JS (RSS is static XML).

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 2),
both confirmed live, neither previously documented (the 2026-10-01 batch that
fixed the identical bug on 4 sibling newspaper sources explicitly left this
module unverified -- see post_and_courier.py's docstring for the full
cross-reference):

1. **The identical severe scope bug found on 4 other `_townnews.py`-based
   newspaper scrapers, confirmed here too.** Greenwood County has never been
   in the 18-county WNC+Upstate-SC flip footprint -- it is explicitly in
   `config.SCOPE_DENY_COUNTIES` -- so every "NOTICE OF SALE" / Master-in-
   Equity row, classified `ListingType.FORECLOSURE_SALE` (a "flip" type) by
   the shared `_townnews._classify()`, is unconditionally rejected by
   `main._flip_outside_footprint()`. This feed 429s aggressively under
   back-to-back queries (confirmed live 2026-10-04, all 4 queries here hit
   it in under a minute), but a single paced fetch of the real
   `q=master+in+equity` feed still returns real current Greenwood rows
   classified `FORECLOSURE_SALE`/county="Greenwood", which reproduce the
   exact same `main._in_scope() -> False` batch-1 found on Aiken/Berkeley/
   Carteret -- same root cause, same shared parser, same fix. Remapped
   after `parse_rss_items()` returns, scoped to this file only.
2. **The same `l=50` volume cap batch 1 found and fixed on the 3 sibling
   TownNews papers, not yet backported here.** This feed's own aggressive
   429ing made a clean side-by-side `l=50` vs `l=100` item-count comparison
   unreliable to capture live this batch (unlike aiken_standard/berkeley_
   independent, where it was), but it is confirmed to be the same TownNews
   platform/section shape as every sibling paper already confirmed to honor
   `l=100` -- bumped for consistency/future-proofing, same reasoning
   batch 1 applied to carolina_coast.py's low-volume feed.
"""
from __future__ import annotations

from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType
from ._townnews import parse_rss_items

log = structlog.get_logger()

_BASE = "https://www.indexjournal.com/classifieds/community/announcements/legal/?f=rss"
FEED_URLS = (
    _BASE + "&l=100&s=start_time&sd=desc",                       # whole legal feed (filtered downstream)
    _BASE + "&q=foreclosure&l=100&s=start_time&sd=desc",
    _BASE + "&q=master+in+equity&l=100&s=start_time&sd=desc",
    _BASE + "&q=trustee&l=100&s=start_time&sd=desc",
)


class IndexJournalForeclosures(BaseScraper):
    slug = "newspapers.index_journal"
    name = "Index-Journal Legal Notices (Greenwood SC)"
    category = "newspaper_legal"
    requires_apify = False
    expected_min_count = 0   # quiet weeks = data reality, not failure
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()
        for url in FEED_URLS:
            try:
                xml = await get_text(url, timeout=30.0)
            except httpx.HTTPStatusError as exc:
                # A 403/429 from this TownNews host (it answers 429 "Too Many Requests"
                # quickly, and get_text has already retried it): the next feed URL on the
                # same host gets the same answer, so stop instead of asking again. Rows
                # already read are kept. (Source-completeness audit 2026-10-08.)
                if exc.response is not None and exc.response.status_code in (403, 429):
                    log.warning("index_journal.blocked_stop", status=exc.response.status_code)
                    break
                continue
            except Exception:
                continue
            if "<item>" not in xml.lower():
                continue
            for li in parse_rss_items(
                xml,
                source_slug=self.slug,
                default_state="SC",
                default_county="Greenwood",
                allowed_states=("SC",),
                sale_location="Greenwood County (Master-in-Equity / Common Pleas)",
            ):
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                # FOUND 2026-10-04: see module docstring -- Greenwood County
                # is never in the 18-county flip footprint, so
                # FORECLOSURE_SALE (flip) is remapped to LIS_PENDENS
                # (non-flip, reaches the board via the unrestricted
                # distressed scope instead).
                if li.listing_type == ListingType.FORECLOSURE_SALE:
                    li.listing_type = ListingType.LIS_PENDENS
                out.append(li)
        log.info("index_journal.fetch_done", count=len(out))
        return out
