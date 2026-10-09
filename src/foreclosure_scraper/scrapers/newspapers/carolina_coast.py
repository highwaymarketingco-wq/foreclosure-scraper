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

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1),
confirmed live, previously undocumented:

1. **A severe, 100%-dead-on-arrival scope bug.** Carteret County is NOT in
   the 18-county WNC+Upstate-SC flip footprint (confirmed: it is not in
   `config`'s footprint list, though it IS in `main.OCEANFRONT_COASTAL_
   COUNTIES`). `_townnews._classify()` returns `ListingType.FORECLOSURE_SALE`
   for the real NC substitute-trustee "Notice of Foreclosure Sale" template
   this feed almost always returns (live-sampled today: both of 2 current
   rows -- "NOTICE OF FORECLOSURE SALE 25SP009924-150 168 SAMPLE RD
   NEWPORT, NC" and a timeshare-lien foreclosure -- classified
   FORECLOSURE_SALE). FORECLOSURE_SALE is a flip type, and
   `main._flip_outside_footprint()` rejects ANY flip-type row outside the
   18-county footprint UNCONDITIONALLY, before the oceanfront/coastal carve-
   outs even run ("however it got its coastal credentials" per that
   function's own comment) -- confirmed live by calling the real
   `main._in_scope()` directly: `county="Carteret", state="NC",
   listing_type=FORECLOSURE_SALE` -> `False`; `listing_type=LIS_PENDENS` ->
   `True` (admitted via the unrestricted distressed scope). So every real row
   this scraper has ever produced was silently dropped at the board gate.
   Remapped to LIS_PENDENS after `parse_rss_items()` returns, scoped to this
   file only (the shared `_townnews._classify()` is untouched -- other
   TownNews papers on this module, including in-footprint ones, were not
   re-verified this batch).
2. **A real, live volume cap**, same root cause as the sibling Post &
   Courier-network papers audited this batch: `l=50` hardcoded, confirmed the
   real server honors `l=100`. Low practical impact here (Carteret's own
   foreclosure volume is tiny -- 2 current rows total today), bumped anyway
   for consistency and to not silently re-cap if volume picks up.

Free, no login, no WAF, no JS for the data we read (RSS is static XML).
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

FEED_URLS = (
    "https://www.carolinacoastonline.com/classifieds/?f=rss&q=foreclosure"
    "&l=100&s=start_time&sd=desc",
    "https://www.carolinacoastonline.com/classifieds/?f=rss&q=substitute+trustee"
    "&l=100&s=start_time&sd=desc",
    "https://www.carolinacoastonline.com/classifieds/?f=rss&q=trustee+sale"
    "&l=100&s=start_time&sd=desc",
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
            except httpx.HTTPStatusError as exc:
                # A 403/429 from this TownNews host (it answers 429 "Too Many Requests"
                # quickly, and get_text has already retried it): the next feed URL on the
                # same host gets the same answer, so stop instead of asking again. Rows
                # already read are kept. (Source-completeness audit 2026-10-08.)
                if exc.response is not None and exc.response.status_code in (403, 429):
                    log.warning("carolina_coast.blocked_stop", status=exc.response.status_code)
                    break
                continue
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
                # FOUND 2026-10-04: see module docstring -- Carteret County is
                # never in the 18-county flip footprint, so FORECLOSURE_SALE
                # (flip) is remapped to LIS_PENDENS (non-flip, reaches the
                # board via the unrestricted distressed scope instead).
                if li.listing_type == ListingType.FORECLOSURE_SALE:
                    li.listing_type = ListingType.LIS_PENDENS
                out.append(li)
        log.info("carolina_coast.fetch_done", count=len(out))
        return out
