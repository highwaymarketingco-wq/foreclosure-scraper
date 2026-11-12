"""national.epa_superfund: fetch() already hardcoded `return []` (dead
endpoint + redundant with counties_generic.epa_frs_sites.py) but never set
disabled=True, so every run reported OUTCOME_ZERO instead of
OUTCOME_DORMANT -- an ambiguous zero. Found via the 2026-10-01 national/reo
per-source extraction audit, same pattern as national.liensnc /
national.probate_foreclosure_leads / national.propwire /
national.legacy_obituaries. No behavior change.

national.seeclickfix's own disabled/dormant coverage moved to
tests/test_seeclickfix.py 2026-10-04 (batch 18): the source was RE-ENABLED
that batch (the lat/lng/radius bug this file used to also cover is fixed,
replaced by a real place_url-based rewrite), so it is no longer a
disabled/dormant source and does not belong in this file.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national import epa_superfund as epa_mod


def test_epa_superfund_disabled_and_dormant():
    assert epa_mod.EPASuperfund.disabled is True
    assert epa_mod.EPASuperfund.disabled_reason

    scraper = epa_mod.EPASuperfund()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()
