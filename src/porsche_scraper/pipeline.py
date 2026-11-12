"""Orchestrator — run every registered scraper, dedupe, apply filters."""
from __future__ import annotations

import asyncio
import logging

from .base import BaseScraper
from .filters import FilterCriteria, filter_listings
from .models import Listing

log = logging.getLogger("porsche_scraper.pipeline")


def dedupe(listings: list[Listing]) -> list[Listing]:
    by_key: dict[str, Listing] = {}
    for l in listings:
        k = l.dedupe_key()
        existing = by_key.get(k)
        if existing is None:
            by_key[k] = l
            continue
        # Prefer the one with a real price and more fields populated.
        if existing.effective_price is None and l.effective_price is not None:
            by_key[k] = l
            continue
        if (l.mileage or 0) > (existing.mileage or 0):
            by_key[k] = l
    return list(by_key.values())


async def run_all(
    scrapers: list[BaseScraper],
    *,
    criteria: FilterCriteria | None = None,
    max_concurrency: int = 4,
) -> list[Listing]:
    sem = asyncio.Semaphore(max_concurrency)

    async def _run(s: BaseScraper) -> list[Listing]:
        async with sem:
            return await s.safe_run()

    results = await asyncio.gather(*(_run(s) for s in scrapers))
    flat: list[Listing] = []
    for res in results:
        flat.extend(res)
    log.info("scraped %d raw listings across %d sources", len(flat), len(scrapers))
    deduped = dedupe(flat)
    log.info("after dedupe: %d", len(deduped))
    filtered = filter_listings(deduped, criteria)
    log.info("after filter: %d match criteria", len(filtered))
    # Sort projects (salvage / rebuilt / damaged) before clean cars, then
    # cheaper-within-tier first so the dashboard surfaces fixers up top.
    tier_order = {"salvage": 0, "rebuilt": 1, "damaged": 2, "clean": 3}
    filtered.sort(key=lambda l: (
        tier_order.get(l.project_tier, 9),
        l.effective_price if l.effective_price is not None else 1e12,
    ))
    return filtered
