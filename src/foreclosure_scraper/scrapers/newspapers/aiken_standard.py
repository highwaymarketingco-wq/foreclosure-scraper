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
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._townnews import parse_rss_items

FEED_URLS = (
    "https://www.postandcourier.com/aikenstandard/classifieds/search/"
    "?f=rss&q=master+in+equity&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/aikenstandard/classifieds/search/"
    "?f=rss&q=foreclosure&l=50&s=start_time&sd=desc",
    "https://www.postandcourier.com/aikenstandard/classifieds/search/"
    "?f=rss&q=trustee&l=50&s=start_time&sd=desc",
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
                out.append(li)
        return out
