"""The Post and Courier (Charleston, SC) — foreclosure legal notices.

The Post & Courier is the legal-notice paper of record for Charleston County,
SC (part of the coastal footprint). It runs on TownNews (TNCMS), whose
legal-classifieds category exposes a free, server-rendered RSS feed. Filtering
that feed for `q=foreclosure` returns only the foreclosure-related notices:
Master-in-Equity sale notices and SC mortgage-foreclosure summonses (Court of
Common Pleas), published days-to-weeks BEFORE the auction — the pre-auction
signal we want.

NOTE (2026-09-14): this scraper's FEED_URLS query one generic classifieds
section that is Charleston-scoped in practice. Berkeley and Dorchester
counties are NOT reliably covered here even though early samples occasionally
included stray Berkeley rows — each of those counties' own local paper
publishes its legal notices under its OWN TownNews section on this same
postandcourier.com domain, which this scraper never queries. They are covered
by dedicated sibling scrapers instead: newspapers.berkeley_independent
(Berkeley) and newspapers.journal_scene (Dorchester). See _townnews.py for the
shared parser both this file and those two reuse. Do not re-add Berkeley/
Dorchester coverage here — it already exists elsewhere.

Verified live (2026-06-25): the foreclosure RSS returned 3 current notices
spanning Charleston + Berkeley counties, each carrying the C/A (case) number,
county, court, and parties. SC sale addresses are then resolved downstream by
the existing case-number / Master-in-Equity enrichers. Any stray non-Charleston
row that slips through this feed is still correctly county-tagged by
_townnews.parse_rss_items's _resolve_county() (falls back to this scraper's
default_county="Charleston" only when no known SC/NC county name is found in
the text at all).

Free, no login, no WAF, no JS for the data we read (RSS is static XML).

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 2),
both confirmed live, neither previously documented (batch 1 fixed the same
bug class on 4 sibling newspaper sources but explicitly left `_townnews.py`'s
shared `_classify()` untouched and did not re-verify the 3 remaining
TownNews-based papers — this is that re-verification):

1. **The identical severe, 100%-dead-on-arrival scope bug as batch 1, this
   time traced to the SHARED `_townnews._classify()` this module calls
   (not a per-scraper bug)**. Every "NOTICE OF SALE" / Master-in-Equity row
   is classified `ListingType.FORECLOSURE_SALE` (a "flip" type), and
   Charleston County has never been in the 18-county WNC+Upstate-SC flip
   footprint (it is explicitly in `config.SCOPE_DENY_COUNTIES`, and
   `main._flip_outside_footprint()` rejects it unconditionally, before any
   oceanfront/downtown-Charleston carve-out even runs). Confirmed live
   2026-10-04: all 9 real current rows sampled across the `master+in+equity`
   and `trustee` feeds (the `foreclosure` feed itself 429'd this run) were
   `FORECLOSURE_SALE` and all 9 came back `main._in_scope() -> False`. One of
   those 9 resolved to county="Dorchester" via `_resolve_county()` -- still
   dropped, same reason. Remapped after `parse_rss_items()` returns, scoped
   to this file only, the exact pattern batch 1 used for aiken_standard.py/
   berkeley_independent.py/carolina_coast.py -- `_townnews._classify()`
   itself is still left untouched (journal_scene.py/index_journal.py share
   it and are fixed identically alongside this file in the same batch).
2. **The same `l=50` volume cap batch 1 found and fixed on the 3 sibling
   TownNews papers, not yet backported here.** Confirmed live 2026-10-04 this
   feed is the same TownNews platform and also honors `l=100`. Bumped.
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

# TownNews legal-classifieds category RSS, foreclosure-filtered.
# `l=100` is the real server cap (confirmed live 2026-10-04 -- see docstring
# point 2); `s=start_time&sd=desc` = newest first.
FEED_URLS = (
    "https://www.postandcourier.com/classifieds_new/community/announcements/"
    "legal/?f=rss&q=foreclosure&l=100&s=start_time&sd=desc",
    # Broader fallback term — catches trustee/MIE notices not literally tagged
    # "foreclosure" in the headline.
    "https://www.postandcourier.com/classifieds_new/community/announcements/"
    "legal/?f=rss&q=master+in+equity&l=100&s=start_time&sd=desc",
    "https://www.postandcourier.com/classifieds_new/community/announcements/"
    "legal/?f=rss&q=trustee&l=100&s=start_time&sd=desc",
)


class PostAndCourierForeclosures(BaseScraper):
    slug = "newspapers.post_and_courier"
    name = "The Post and Courier Legal Notices (Charleston SC)"
    category = "newspaper_legal"
    requires_apify = False
    # Legal-notice volume swings week to week; a quiet week with 0 foreclosure
    # notices is data reality, not a scraper failure. A real regression here is
    # the RSS endpoint 404ing / returning no <item> elements at all (which the
    # block-signal + outcome classifier surface separately).
    expected_min_count = 0
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
                    log.warning("post_and_courier.blocked_stop", status=exc.response.status_code)
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
                default_county="Charleston",
                allowed_states=("SC",),
                sale_location="Charleston County (Master-in-Equity / Common Pleas)",
            ):
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                # FOUND 2026-10-04: see module docstring -- Charleston County
                # is never in the 18-county flip footprint (explicitly
                # deny-listed), so FORECLOSURE_SALE (flip) is remapped to
                # LIS_PENDENS (non-flip, reaches the board via the
                # unrestricted distressed scope instead).
                if li.listing_type == ListingType.FORECLOSURE_SALE:
                    li.listing_type = ListingType.LIS_PENDENS
                out.append(li)
        log.info("post_and_courier.fetch_done", count=len(out))
        return out
