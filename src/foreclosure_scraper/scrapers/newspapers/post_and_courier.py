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
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._townnews import parse_rss_items

# TownNews legal-classifieds category RSS, foreclosure-filtered.
# `l=50` raises the item cap; `s=start_time&sd=desc` = newest first.
FEED_URLS = (
    "https://www.postandcourier.com/classifieds_new/community/announcements/"
    "legal/?f=rss&q=foreclosure&l=50&s=start_time&sd=desc",
    # Broader fallback term — catches trustee/MIE notices not literally tagged
    # "foreclosure" in the headline.
    "https://www.postandcourier.com/classifieds_new/community/announcements/"
    "legal/?f=rss&q=master+in+equity&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/classifieds_new/community/announcements/"
    "legal/?f=rss&q=trustee&l=50&s=start_time&sd=desc",
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
                out.append(li)
        return out
