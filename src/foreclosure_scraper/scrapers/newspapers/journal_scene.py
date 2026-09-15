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
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._townnews import parse_rss_items

FEED_URLS = (
    "https://www.postandcourier.com/journal-scene/classifieds/community/announcements/"
    "legal/?f=rss&q=master+in+equity&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/journal-scene/classifieds/community/announcements/"
    "legal/?f=rss&q=foreclosure&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/journal-scene/classifieds/community/announcements/"
    "legal/?f=rss&q=trustee&l=50&s=start_time&sd=desc",
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
                out.append(li)
        return out
