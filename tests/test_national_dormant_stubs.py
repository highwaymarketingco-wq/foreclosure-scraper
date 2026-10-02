"""national.liensnc and national.probate_foreclosure_leads: both scrapers'
fetch() bodies already hardcoded `return []` (a login wall for liensnc, a
paid-service opt-out for probate_foreclosure_leads) but neither set
disabled=True, so every run reported OUTCOME_ZERO ("ran clean but returned
0 rows") instead of OUTCOME_DORMANT. That is an ambiguous zero -- it reads
identically to a real search that found nothing -- which is exactly the
"silent success" failure mode CLAUDE.md calls out as this codebase's actual
failure mode. Found via the 2026-10-01 national/reo per-source extraction
audit. No behavior change: both fetch() bodies already never touched the
network; this only makes safe_run()'s outcome honest about WHY it is zero.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import liensnc as liensnc_mod
from foreclosure_scraper.scrapers.national import (
    probate_foreclosure_leads as probate_mod,
)


def test_liensnc_disabled_and_dormant():
    assert liensnc_mod.LiensNCScraper.disabled is True
    assert liensnc_mod.LiensNCScraper.disabled_reason

    scraper = liensnc_mod.LiensNCScraper()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()


def test_probate_foreclosure_leads_disabled_and_dormant():
    assert probate_mod.ProbateForeclosureLeads.disabled is True
    assert probate_mod.ProbateForeclosureLeads.disabled_reason

    scraper = probate_mod.ProbateForeclosureLeads()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()
