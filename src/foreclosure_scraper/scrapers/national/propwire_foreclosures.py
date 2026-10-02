"""Propwire pre-foreclosure leads — gracefully empty (no spend).

Propwire is a paid service ($0.007/record via Apify actor). The user has
explicitly opted out of paid services. This scraper is kept registered so
removing it doesn't break orchestrator expectations, but returns [] silently.

To re-enable when the user wants to pay: revert to the Apify implementation
in git history.
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


class Propwire(BaseScraper):
    slug = "national.propwire"
    name = "Propwire Pre-foreclosure"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0
    # DISABLED 2026-10-01 (national/reo per-source audit): fetch() already
    # hardcoded `return []` (paid Apify actor, opted out) but never set
    # disabled=True, so every run reported OUTCOME_ZERO ("ran clean but
    # returned 0 rows") instead of OUTCOME_DORMANT -- an ambiguous zero. No
    # behavior change. Separately, Propwire's own site is DataDome-walled
    # (docs/HERMES.md Section 12 WONT list) even past the paid-actor
    # question, so this stays off either way.
    disabled = True
    disabled_reason = (
        "paid Apify actor, opted out; site itself is also DataDome-walled "
        "(docs/HERMES.md Section 12 WONT)"
    )

    async def fetch(self) -> Iterable[Listing]:
        log.info("propwire.skipped", reason="paid service; user opted out of spend")
        return []
