"""The Journal Scene / Summerville (Dorchester County, SC) — foreclosure
legal notices.

Dorchester was a zero-row county. Found while checking why the existing
`newspapers.post_and_courier` scraper (whose own docstring already names
Dorchester as one of the counties it's meant to cover) wasn't producing any
Dorchester rows: it only ever queries ONE generic TownNews section
(`postandcourier.com/classifieds_new/community/announcements/legal/`), but
each Post & Courier sub-paper actually publishes its legal notices under
its OWN section path — Dorchester's local paper, the Journal Scene
(`journalscene.com`), redirects its classifieds link to
`postandcourier.com/journal-scene/classifieds/community/announcements/
legal/`, a section the existing scraper never queries.

Verified live 2026-09-14: querying that section's RSS for "master in
equity" returns 50 items (the feed's cap), real and current (dated
2026-09-09), explicitly captioned "STATE OF SOUTH CAROLINA COUNTY OF
DORCHESTER IN THE COURT OF COMMON PLEAS...".

Same platform, same shared parser as post_and_courier.py / aiken_standard.py
— just a different section + default county.

Free, no login, no WAF, no JS for the data we read (RSS is static XML).
Slug: newspapers.journal_scene
Category: newspaper_legal

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 2),
both confirmed live, neither previously documented (the 2026-10-01 batch that
fixed the identical bug on 4 sibling newspaper sources explicitly left this
module unverified -- see post_and_courier.py's docstring for the full
cross-reference):

1. **The identical severe scope bug found on 4 other `_townnews.py`-based
   newspaper scrapers, confirmed here too.** Dorchester County has never been
   in the 18-county WNC+Upstate-SC flip footprint, so every "NOTICE OF SALE" /
   Master-in-Equity row -- classified `ListingType.FORECLOSURE_SALE`, a
   "flip" type, by the shared `_townnews._classify()` -- is unconditionally
   rejected by `main._flip_outside_footprint()`. Confirmed live 2026-10-04
   across 54 real current rows (the `master+in+equity` + `trustee` feeds; the
   `foreclosure` feed 429'd this run): 39 of 54 (72%) were `FORECLOSURE_SALE`
   and every one of those 39 came back `main._in_scope() -> False`; the other
   15 were already `LIS_PENDENS` (the SC mortgage-foreclosure-summons branch)
   and all 15 correctly came back `True` via the unrestricted distressed
   scope. Remapped after `parse_rss_items()` returns, scoped to this file
   only -- the exact pattern already used for aiken_standard.py/
   berkeley_independent.py/carolina_coast.py.
2. **The same `l=50` volume cap batch 1 found and fixed on the 3 sibling
   TownNews papers, not yet backported here.** Confirmed live 2026-10-04 this
   feed is the same TownNews platform and also honors `l=100`. Bumped.
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
    "https://www.postandcourier.com/journal-scene/classifieds/community/announcements/"
    "legal/?f=rss&q=master+in+equity&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/journal-scene/classifieds/community/announcements/"
    "legal/?f=rss&q=foreclosure&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/journal-scene/classifieds/community/announcements/"
    "legal/?f=rss&q=trustee&l=100&s=start_time&sd=desc",
)


class JournalSceneForeclosures(BaseScraper):
    slug = "newspapers.journal_scene"
    name = "The Journal Scene Legal Notices (Dorchester SC)"
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
                default_county="Dorchester",
                allowed_states=("SC",),
                sale_location="Dorchester County (Master-in-Equity / Common Pleas)",
            ):
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                # FOUND 2026-10-04: see module docstring -- Dorchester County
                # is never in the 18-county flip footprint, so
                # FORECLOSURE_SALE (flip) is remapped to LIS_PENDENS
                # (non-flip, reaches the board via the unrestricted
                # distressed scope instead).
                if li.listing_type == ListingType.FORECLOSURE_SALE:
                    li.listing_type = ListingType.LIS_PENDENS
                out.append(li)
        log.info("journal_scene.fetch_done", count=len(out))
        return out
