"""Carolina Coast Online / Carteret County News-Times (NC) — foreclosure notices.

The News-Times is the legal-notice paper of record for Carteret County, NC
(Crystal Coast: Beaufort, Morehead City, Harkers Island, Atlantic Beach) — part
of the NC-coast footprint. It runs on TownNews (TNCMS), whose legal-classifieds
category exposes a free, server-rendered RSS feed. Filtering for `q=foreclosure`
returns NC substitute-trustee foreclosure-sale notices (`Notice of Substitute
Trustee's Foreclosure Sale of Real Property`), published BEFORE the auction.

Verified live (2026-06-25): the foreclosure RSS returned a current substitute-
trustee sale notice with the case number (26SP000053-150) AND the full property
address (294 Cape Lookout Dr, Harkers Island, NC) right in the headline — a
clean pre-auction lead. NC notices reliably carry the street address in the
title because trustee sales are advertised by-property.

Free, no login, no WAF, no JS for the data we read (RSS is static XML).
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._townnews import parse_rss_items

FEED_URLS = (
    "https://www.carolinacoastonline.com/classifieds/?f=rss&q=foreclosure"
    "&l=50&s=start_time&sd=desc",
    "https://www.carolinacoastonline.com/classifieds/?f=rss&q=substitute+trustee"
    "&l=50&s=start_time&sd=desc",
    "https://www.carolinacoastonline.com/classifieds/?f=rss&q=trustee+sale"
    "&l=50&s=start_time&sd=desc",
)


class CarolinaCoastForeclosures(BaseScraper):
    slug = "newspapers.carolina_coast"
    name = "Carteret County News-Times Legal Notices (Carteret NC)"
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
                default_state="NC",
                default_county="Carteret",
                allowed_states=("NC",),
                sale_location="Carteret County Courthouse, Beaufort NC",
            ):
                if li.source_url in seen_urls:
                    continue
                seen_urls.add(li.source_url)
                out.append(li)
        return out
