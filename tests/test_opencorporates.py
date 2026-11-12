"""OpenCorporates API (enrichment helper, not a lead source).

2026-10-01 per-source audit: confirmed live that the free/anonymous tier
this module's docstring used to describe no longer exists -- an
unauthenticated request to the real endpoint now returns HTTP 401
("Invalid Api Token"). This also means the module was already in direct
conflict with CLAUDE.md / HERMES.md's own hard rule naming OpenCorporates
as a paid service explicitly out of scope for this free-only engine. No
fix is possible without paying for API access, which this project's rules
do not allow -- these tests guard the honest, safe-failure behavior.

FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 17), same bug
class as law_firms.korn's 2026-10-01 fix and this same batch's
national.nc_sos_ucc fix: `disabled` was never set to True, so this scraper
(auto-registered into the normal scrape loop by scrapers/_registry.py's
category-blind discover()) recorded the ambiguous OUTCOME_ZERO every
orchestration cycle instead of the accurate OUTCOME_DORMANT. Fixed by
setting disabled = True.
"""
import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national.opencorporates import (
    OpenCorporatesScraper,
)


def test_disabled_with_a_reason():
    s = OpenCorporatesScraper()
    assert s.disabled is True
    assert s.disabled_reason  # non-empty, explains the paid-API finding


def test_standalone_fetch_is_a_no_op():
    rows = asyncio.run(OpenCorporatesScraper().fetch())
    assert rows == []


def test_safe_run_reports_dormant_not_zero():
    s = OpenCorporatesScraper()
    out = asyncio.run(s.safe_run())
    assert out == []
    assert s.last_outcome == OUTCOME_DORMANT
    assert "disabled" in s.last_reason.lower()


def test_search_entity_short_name_returns_none_without_a_network_call():
    result = asyncio.run(OpenCorporatesScraper.search_entity("AB"))
    assert result is None


def test_search_entity_empty_name_returns_none():
    result = asyncio.run(OpenCorporatesScraper.search_entity(""))
    assert result is None
