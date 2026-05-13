"""Detail-page fetcher for extracting judgment_amount from Notice of Sale text.

The scrapers in scrapers/law_firms/ extract structured data from list-page
table cells but NOT the full Notice of Sale text where the judgment amount
appears (verified via diagnostic stats: text_no_match=717/717 in run #11).
Each listing has a detail-page URL captured as `source_url` — fetching
that page exposes the full notice text with phrases like:

  "Pursuant to a judgment entered in [court] in the amount of $X.XX..."
  "money judgment in the amount of $X..."
  "outstanding principal balance of $X..."

We then re-run the existing judgment_amount extractor on the fetched text.

Cost control:
  - Only fetches listings where judgment_amount is currently None
  - Only fetches when source_url looks like a real per-listing detail page
    (not a list-page index URL — heuristic checks 'foreclosure-sale/<id>'
    style URL paths)
  - Cap via JUDGMENT_DETAIL_MAX_FETCHES env (default 200)
  - Prioritizes by sale_date proximity (imminent sales fetched first)
  - Concurrency cap (8 in-flight) to avoid hammering law firm sites

Cost estimate: 200 GETs/run × 4 runs/week = 800 fetches/week. Each ~1KB
response. Negligible bandwidth, zero $ cost.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Optional

import httpx
import structlog
from selectolax.parser import HTMLParser

from .enrichment_judgment_amount import _extract_from_text
from .models import Listing

log = structlog.get_logger()


# Default cap — bounded so a runaway scraper can't blow the runtime budget
DEFAULT_MAX_FETCHES = int(os.environ.get("JUDGMENT_DETAIL_MAX_FETCHES", "200"))
CONCURRENCY = int(os.environ.get("JUDGMENT_DETAIL_CONCURRENCY", "8"))
FETCH_TIMEOUT_S = float(os.environ.get("JUDGMENT_DETAIL_TIMEOUT_S", "20"))


# URL heuristics: per-listing detail URLs typically have a numeric or
# slug ID at the end of a known per-listing path. List-page / homepage
# URLs are skipped to avoid burning fetches on no-judgment-text pages.
_DETAIL_URL_PATTERNS = [
    re.compile(r"/foreclosure-sale/[a-z0-9_-]+/?$", re.I),
    re.compile(r"/sale-day-listings-selection/foreclosure-listings", re.I),
    re.compile(r"/NCfcSalesList\.aspx", re.I),  # Hutchens (list — full notices inline in cell)
    re.compile(r"/SCfcSalesList\.aspx", re.I),
    re.compile(r"/foreclosure-listings/[a-z0-9_-]+", re.I),
    re.compile(r"/sale[/_-]?detail", re.I),
    re.compile(r"/notice[/_-]?[a-z0-9_-]+", re.I),
]


def _looks_like_detail_page(url: Optional[str]) -> bool:
    """Returns True only when the URL looks like a per-listing detail
    page worth fetching. Skips bare list pages + homepages."""
    if not url:
        return False
    for pat in _DETAIL_URL_PATTERNS:
        if pat.search(url):
            return True
    return False


# Sources where we know a detail page exists. Used as an additional gate
# in case the URL pattern check is too restrictive. Add to this set as
# we verify new law-firm detail-page support.
_DETAIL_PAGE_SOURCES = {
    "law_firms.brock_scott",
    "law_firms.hutchens",
    "law_firms.bell_carrington",
    "law_firms.finkel",
    "law_firms.aldridge_pite",
    "law_firms.kania",
}


def _priority(li: Listing) -> tuple:
    """Sort key: imminent sales fetched first. The closer to sale_date,
    the more actionable the judgment amount is for the investor."""
    if li.sale_date is None:
        return (3, 0)
    sale = li.sale_date
    if hasattr(sale, "tzinfo") and sale.tzinfo:
        sale = sale.replace(tzinfo=None)
    now = datetime.utcnow()
    days = (sale - now).days
    if 0 <= days <= 14:
        return (0, days)       # within 2 weeks — highest urgency
    if 14 < days <= 60:
        return (1, days)
    if days < 0:
        return (2, abs(days))  # past sale, lower priority
    return (3, days)


async def _fetch_text(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """GET the detail page and return its visible text content. Returns
    None on any failure (404, timeout, blocked, etc.) — caller treats
    as 'no extra signal' and falls through to existing data."""
    try:
        r = await client.get(url, follow_redirects=True, timeout=FETCH_TIMEOUT_S)
        if r.status_code != 200 or not r.text or len(r.text) < 500:
            return None
        tree = HTMLParser(r.text)
        if tree.body is None:
            return None
        # Just the visible text — strip script/style content via selectolax
        return tree.body.text(separator=" ", strip=True)
    except Exception as exc:
        log.debug("judgment_detail.fetch_fail", url=url[:120], error=str(exc)[:120])
        return None


async def enrich_judgment_amount_via_detail_pages(
    listings: list[Listing],
    max_fetches: Optional[int] = None,
) -> dict:
    """Fetch per-listing detail pages and re-run the judgment-amount
    extractor on the fetched text. Mutates listings in place to
    populate li.judgment_amount when a match is found.

    Returns a stats dict suitable for run_health.json.
    """
    stats = {
        "candidates": 0,
        "fetched": 0,
        "matched": 0,
        "skipped_capped": 0,
        "matched_by_source": {},
    }

    if max_fetches is None:
        max_fetches = DEFAULT_MAX_FETCHES

    # Eligible: judgment_amount missing + detail-page URL present +
    # source is one we know has fetchable detail pages.
    eligible = [
        li for li in listings
        if (li.judgment_amount is None or li.judgment_amount == 0)
        and li.source in _DETAIL_PAGE_SOURCES
        and _looks_like_detail_page(li.source_url)
    ]
    stats["candidates"] = len(eligible)
    if not eligible:
        log.info("judgment_detail.no_candidates")
        return stats

    eligible.sort(key=_priority)
    targets = eligible[:max_fetches]
    stats["skipped_capped"] = max(0, len(eligible) - len(targets))

    log.info(
        "judgment_detail.start",
        candidates=len(eligible),
        targets=len(targets),
        max_fetches=max_fetches,
    )

    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT_S,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    ) as client:

        async def one(li: Listing) -> None:
            async with sem:
                text = await _fetch_text(client, li.source_url)
            if text:
                stats["fetched"] += 1
                # Stash the fetched text into raw so subsequent enrichments
                # (description display, future text-mining) can re-use it.
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw.setdefault("detail_page", {})["text"] = text[:5000]
                amt = _extract_from_text(text)
                if amt is not None:
                    li.judgment_amount = round(amt, 2)
                    stats["matched"] += 1
                    src = li.source or "unknown"
                    stats["matched_by_source"][src] = stats["matched_by_source"].get(src, 0) + 1

        await asyncio.gather(*(one(li) for li in targets))

    log.info("judgment_detail.done", **stats)
    return stats
