"""Probate foreclosure leads — gracefully empty (no Apify, no spend).

Original used jungle_synthesizer/probate-foreclosure-leads-scraper Apify
actor. User has opted out of paid services. Probate-driven distress is
indirectly captured via:
  - law_firms.* scrapers when probate-defendants surface in foreclosure
  - public_notices.ncnotices for "estate of" / probate language matches
  - bankruptcy enrichment when heirs file Chapter 7

Returns [] silently.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class ProbateForeclosureLeads(BaseScraper):
    slug = "national.probate_foreclosure_leads"
    name = "Probate Foreclosure Leads"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0
    # DISABLED 2026-10-01 (national/reo per-source audit): fetch() already
    # hardcoded `return []` (paid Apify actor, opted out) but never set
    # disabled=True, so every run reported OUTCOME_ZERO ("ran clean but
    # returned 0 rows") instead of OUTCOME_DORMANT -- an ambiguous zero that
    # looks identical to a real search finding nothing. No behavior change;
    # this only makes the run report honest about WHY it is zero.
    disabled = True
    disabled_reason = (
        "paid Apify actor (jungle_synthesizer/probate-foreclosure-leads-scraper), "
        "opted out; signal captured via law_firms.* + public_notices.ncnotices instead"
    )

    async def fetch(self) -> Iterable[Listing]:
        log.info("probate.skipped",
                 reason="paid Apify actor; probate signal captured via law firms + ncnotices")
        return []
