"""The Berkeley Independent (Berkeley County, SC) — foreclosure legal
notices.

Berkeley was stuck at 2 board rows. Found the same way as Dorchester's
journal_scene.py: the existing `newspapers.post_and_courier` scraper's own
docstring names Berkeley as a county it's meant to cover, but only queries
one generic TownNews section that doesn't include it. Berkeley's local
paper, the Berkeley Independent (`berkeleyind.com`), redirects its
classifieds link to `postandcourier.com/berkeley-independent/classifieds/
community/announcements/legal/`, a section the existing scraper never
queries.

Verified live 2026-09-14: querying that section's RSS for "master in
equity" / "foreclosure" returns 50 items each (the feed's cap), real and
current notices.

Same platform, same shared parser as post_and_courier.py / aiken_standard.py
/ journal_scene.py — just a different section + default county.

Free, no login, no WAF, no JS for the data we read (RSS is static XML).
Slug: newspapers.berkeley_independent
Category: newspaper_legal

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1),
both confirmed live, neither previously documented -- the exact same two
findings as the sibling `aiken_standard.py` (same Post & Courier TownNews
backend, same shared parser):

1. **A severe, 100%-dead-on-arrival scope bug.** `_townnews._classify()`
   classifies the SC "Notice of Sale" / Master-in-Equity form as
   `ListingType.FORECLOSURE_SALE`, a flip type gated to the narrow 18-county
   footprint by `main._flip_outside_footprint()`. Berkeley County has never
   been in that footprint -- confirmed live by calling the real
   `main._in_scope()`: `county="Berkeley", state="SC",
   listing_type=FORECLOSURE_SALE` -> `False`, `listing_type=LIS_PENDENS` ->
   `True`. Every FORECLOSURE_SALE row this scraper has produced was silently
   dropped at the board gate. Remapped to LIS_PENDENS after
   `parse_rss_items()` returns, scoped to this file only (the shared
   `_townnews._classify()` is untouched -- other papers on the same backend
   were not re-verified this batch).
2. **A real, live, current-data volume cap.** `l=50` is hardcoded; the real
   server accepts (and returns) up to `l=100` -- confirmed live 2026-10-04:
   the `foreclosure` query alone returns 50 rows at `l=50` vs 74 at `l=100`,
   with 25 of those 74 real, current rows absent from the `l=50` response
   entirely (not just reordered). Bumped to the real server max.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType
from ._townnews import parse_rss_items

log = structlog.get_logger()

FEED_URLS = (
    "https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/"
    "legal/?f=rss&q=master+in+equity&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/"
    "legal/?f=rss&q=foreclosure&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/"
    "legal/?f=rss&q=trustee&l=100&s=start_time&sd=desc",
)


class BerkeleyIndependentForeclosures(BaseScraper):
    slug = "newspapers.berkeley_independent"
    name = "The Berkeley Independent Legal Notices (Berkeley SC)"
    category = "newspaper_legal"
    requires_apify = False
    expected_min_count = 0
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()
        for url in FEED_URLS:
            try:
                xml = await get_text(url, timeout=30.0)
            except Exception:
                continue
            if "<item>" not in xml.lower():
                continue
            for li in parse_rss_items(
                xml,
                source_slug=self.slug,
                default_state="SC",
                default_county="Berkeley",
                allowed_states=("SC",),
                sale_location="Berkeley County (Master-in-Equity / Common Pleas)",
            ):
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                # FOUND 2026-10-04: see module docstring -- Berkeley County is
                # never in the 18-county flip footprint, so FORECLOSURE_SALE
                # (flip) is remapped to LIS_PENDENS (non-flip, reaches the
                # board via the unrestricted distressed scope instead).
                if li.listing_type == ListingType.FORECLOSURE_SALE:
                    li.listing_type = ListingType.LIS_PENDENS
                out.append(li)
        log.info("berkeley_independent.fetch_done", count=len(out))
        return out
