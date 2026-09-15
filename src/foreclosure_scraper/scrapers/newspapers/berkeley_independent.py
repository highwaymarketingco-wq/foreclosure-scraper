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
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._townnews import parse_rss_items

FEED_URLS = (
    "https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/"
    "legal/?f=rss&q=master+in+equity&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/"
    "legal/?f=rss&q=foreclosure&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/"
    "legal/?f=rss&q=trustee&l=50&s=start_time&sd=desc",
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
                out.append(li)
        return out
