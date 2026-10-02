"""national.epa_superfund and national.seeclickfix: both scrapers' fetch()
bodies already hardcoded `return []` (epa_superfund: dead endpoint +
redundant with counties_generic.epa_frs_sites.py; seeclickfix: confirmed
garbage emitter, geo-filter silently ignored) but neither set disabled=True,
so every run reported OUTCOME_ZERO instead of OUTCOME_DORMANT -- an
ambiguous zero. Found via the 2026-10-01 national/reo per-source extraction
audit, same pattern as national.liensnc / national.probate_foreclosure_leads
/ national.propwire / national.legacy_obituaries. No behavior change.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import epa_superfund as epa_mod
from foreclosure_scraper.scrapers.national import seeclickfix as scf_mod


def test_epa_superfund_disabled_and_dormant():
    assert epa_mod.EPASuperfund.disabled is True
    assert epa_mod.EPASuperfund.disabled_reason

    scraper = epa_mod.EPASuperfund()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()


def test_seeclickfix_disabled_and_dormant():
    assert scf_mod.SeeClickFixScraper.disabled is True
    assert scf_mod.SeeClickFixScraper.disabled_reason

    scraper = scf_mod.SeeClickFixScraper()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()
