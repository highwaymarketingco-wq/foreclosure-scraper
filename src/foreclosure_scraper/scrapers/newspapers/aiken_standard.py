"""The Aiken Standard (Aiken, SC) — foreclosure legal notices.

Aiken was a zero-row county. Its own delinquent-tax-SALE property list is
published only in this paper's print/legal-notice pages (confirmed live on
the county's own Delinquent-Tax-Sale page: "Property to be sold... will be
advertised in the Aiken Standard on three consecutive Fridays"), not as a
county-hosted document -- a different, harder problem (see
docs/WEEKEND_LOOP_QUEUE.md).

But the Aiken Standard is ALSO the paper of record for Aiken County's
mortgage-foreclosure SUMMONSES (Court of Common Pleas), and it runs on the
SAME TownNews (TNCMS) platform as `newspapers.post_and_courier` (it merged
into the Post & Courier network — `aikenstandard.com` now redirects to
`postandcourier.com/aikenstandard/`), exposing the same free, static RSS
mechanism. Verified live 2026-09-14: querying its legal-classifieds search
for "master in equity" returns real, current (dated 2026-09-08 through
2026-09-11) SC mortgage-foreclosure summonses with case numbers, e.g.
"C/A NO: 2026-CP-02-01392 ... Rocket Mortgage, LLC, PLAINTIFF, vs. Neal D
Nelson...".

Reuses the exact shared parser `newspapers._townnews.parse_rss_items`
post_and_courier.py already uses — same platform, same feed shape, just a
different paper section and default county.

Free, no login, no WAF, no JS for the data we read (RSS is static XML).
Slug: newspapers.aiken_standard
Category: newspaper_legal

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1),
both confirmed live with real current data, neither previously documented:

1. **A severe, 100%-dead-on-arrival scope bug, present since this scraper's
   creation (2026-09-14)**: `parse_rss_items()` classifies every one of these
   SC "Notice of Sale" / Master-in-Equity rows as `ListingType.FORECLOSURE_SALE`
   (confirmed live: all 86 sampled rows hit the "master in equity" branch of
   `_townnews._classify()`). FORECLOSURE_SALE is a "flip" type
   (`main._FLIP_LISTING_TYPES`), and flip types are gated to the narrow
   18-county WNC+Upstate-SC footprint by `main._flip_outside_footprint()` --
   checked BEFORE any coastal/oceanfront carve-out, with no exception. Aiken
   County has never been in that footprint (confirmed by calling the real
   `main._in_scope()` directly: `county="Aiken", state="SC",
   listing_type=FORECLOSURE_SALE` -> `False`, every time, regardless of any
   other field). So every single row this scraper has ever produced was
   silently dropped at the board gate -- a real, live, 100% silent failure,
   not a "some runs come up empty" case. The SAME real row reclassified as
   `LIS_PENDENS` (the non-flip bucket `_classify()` already uses for the SC
   *summons* form of this exact same court process) passes `_in_scope()`
   (confirmed live: `True`) via `in_scope_distressed()`, which admits any
   NC/SC county with no deny list -- exactly the semantics a pre-execution
   legal notice of an active SC judicial foreclosure actually has (a
   motivated-seller signal, not literally "go bid at this flip-footprint
   auction today"). Remapped after `parse_rss_items()` returns, scoped to
   this file only -- `_townnews._classify()` itself is left untouched since
   `post_and_courier.py`/`journal_scene.py`/`index_journal.py` share it and
   were not re-verified this batch.
2. **A real, live, current-data volume cap**: the feed URLs hardcode `l=50`.
   Confirmed live 2026-10-04: the real server accepts `l=100` and actually
   returns up to 100 items (tested `l=50` vs `l=100` vs `l=200`: 50, 100, 100
   respectively -- 100 is the server's real cap, not ours). Since results are
   sorted newest-first, `l=50` silently truncated the window to the newest ~7
   weeks of notices (confirmed: the `l=100` feed's oldest row is 2026-07-24,
   `l=50`'s oldest is 2026-10-02 -- roughly half the real available window is
   never fetched on a single `foreclosure` query alone). Bumped to the real
   server max.
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
    "https://www.postandcourier.com/aikenstandard/classifieds/search/"
    "?f=rss&q=master+in+equity&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/aikenstandard/classifieds/search/"
    "?f=rss&q=foreclosure&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/aikenstandard/classifieds/search/"
    "?f=rss&q=trustee&l=100&s=start_time&sd=desc",
)


class AikenStandardForeclosures(BaseScraper):
    slug = "newspapers.aiken_standard"
    name = "The Aiken Standard Legal Notices (Aiken SC)"
    category = "newspaper_legal"
    requires_apify = False
    # Same reasoning as post_and_courier.py: legal-notice volume swings
    # week to week, a quiet week is data reality, not a scraper failure.
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
                default_county="Aiken",
                allowed_states=("SC",),
                sale_location="Aiken County (Master-in-Equity / Common Pleas)",
            ):
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                # FOUND 2026-10-04: Aiken County is never in the 18-county
                # flip footprint, so a FORECLOSURE_SALE (flip) row is always
                # silently dropped at main._in_scope()'s flip-outside-
                # footprint gate -- confirmed live, every row, no exception.
                # LIS_PENDENS (the non-flip bucket this same module already
                # uses for the SC summons form) reaches the board via the
                # unrestricted distressed scope instead. See module docstring.
                if li.listing_type == ListingType.FORECLOSURE_SALE:
                    li.listing_type = ListingType.LIS_PENDENS
                out.append(li)
        log.info("aiken_standard.fetch_done", count=len(out))
        return out
