"""OpenCorporates API (enrichment helper, not a lead source).

2026-10-01 per-source audit: confirmed live that the free/anonymous tier
this module's docstring used to describe no longer exists -- an
unauthenticated request to the real endpoint now returns HTTP 401
("Invalid Api Token"). This also means the module was already in direct
conflict with CLAUDE.md / HERMES.md's own hard rule naming OpenCorporates
as a paid service explicitly out of scope for this free-only engine. No
fix is possible without paying for API access, which this project's rules
do not allow -- these tests guard the honest, safe-failure behavior.
"""
import asyncio

from foreclosure_scraper.scrapers.national.opencorporates import (
    OpenCorporatesScraper,
)


def test_standalone_fetch_is_a_no_op():
    rows = asyncio.run(OpenCorporatesScraper().fetch())
    assert rows == []


def test_search_entity_short_name_returns_none_without_a_network_call():
    result = asyncio.run(OpenCorporatesScraper.search_entity("AB"))
    assert result is None


def test_search_entity_empty_name_returns_none():
    result = asyncio.run(OpenCorporatesScraper.search_entity(""))
    assert result is None
