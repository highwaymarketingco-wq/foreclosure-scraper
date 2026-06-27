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
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._townnews import parse_rss_items

_BASE = "https://www.indexjournal.com/classifieds/community/announcements/legal/?f=rss"
FEED_URLS = (
    _BASE + "&l=50&s=start_time&sd=desc",                       # whole legal feed (filtered downstream)
    _BASE + "&q=foreclosure&l=50&s=start_time&sd=desc",
    _BASE + "&q=master+in+equity&l=50&s=start_time&sd=desc",
    _BASE + "&q=trustee&l=50&s=start_time&sd=desc",
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
                out.append(li)
        return out
