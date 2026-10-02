"""national.loopnet: 2026-10-01 national/reo per-source extraction audit.

Confirmed live both ways this module reaches LoopNet are dead: the homepage
returns HTTP 403 (active WAF block) via curl_cffi Chrome impersonation, and
every per-city URL this module requests returns HTTP 404 (the URL pattern
no longer exists, a platform redesign). Reconfirms docs/HERMES.md Section
12's existing LoopNet CANT entry. Disabled via disabled=True/disabled_reason
so safe_run() never attempts the dead network calls.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import loopnet as m


def test_disabled_and_dormant():
    assert m.LoopNetScraper.disabled is True
    assert m.LoopNetScraper.disabled_reason

    scraper = m.LoopNetScraper()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()
