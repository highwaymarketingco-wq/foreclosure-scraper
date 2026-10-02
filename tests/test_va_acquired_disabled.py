"""national.va_acquired: 2026-10-01 national/reo per-source extraction audit.

Confirmed live both candidate URLs are dead: VA_URL is a genuine HTTP 404
(and was never even fetched by fetch(), which only ever requests
BANK_REO_URL); BANK_REO_URL returns HTTP 200 but the body is VA's own
site-wide 404 template -- a silent fake-404 that looks identical to a
legitimate empty search in the logs. Also redundant with reo.vrm_va_reo
(VRM Properties, the VA's current REO vendor), confirmed live the same day
to return 193 real NC+SC rows via a working path. Disabled via
disabled=True/disabled_reason.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import va_acquired as m


def test_disabled_and_dormant():
    assert m.VAAcquired.disabled is True
    assert m.VAAcquired.disabled_reason

    scraper = m.VAAcquired()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()
