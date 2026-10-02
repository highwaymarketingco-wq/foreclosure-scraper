"""national.legacy_obituaries: fetch() already hardcoded `return []` (see
module docstring: confirmed garbage emitter, 2026-09-15) but never set
disabled=True, so every run reported OUTCOME_ZERO instead of
OUTCOME_DORMANT -- an ambiguous zero. Found via the 2026-10-01 national/reo
per-source extraction audit, same pattern as national.liensnc /
national.probate_foreclosure_leads / national.propwire. No behavior change.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import legacy_obituaries as m


def test_disabled_and_dormant():
    assert m.LegacyObituariesScraper.disabled is True
    assert m.LegacyObituariesScraper.disabled_reason

    scraper = m.LegacyObituariesScraper()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()
