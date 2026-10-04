"""SC SOS business entity search (enrichment helper, not a lead source).

2026-10-01 per-source audit: confirmed the hardcoded _SEARCH_URL is dead
(live HTTP 404) and that the real current search flow is gated by a real
Google reCAPTCHA on submission (a populated div.g-recaptcha with a real
data-sitekey, confirmed live) -- matching the operator's own prior note
that SC SOS is captcha-walled. Per this codebase's compliance line, a
CAPTCHA is a wall: it is not solved or routed around. These tests guard
the honest, safe-failure behavior rather than pretending the lookup works.

2026-10-04 (batch 18): re-verified the reCAPTCHA wall live via a real
browser session (same sitekey, now also confirmed to render visibly after
a real search submission, not just present-but-hidden on load). Also found
this module never set `disabled = True` despite being auto-registered into
the normal scrape loop (scrapers/_registry.py discover() has no category
filter) -- the exact same bug class as the 2026-10-04 opencorporates/
nc_sos_ucc fixes. Fixed; added test coverage for it below.
"""
import asyncio

from foreclosure_scraper.scrapers.national.sc_sos_entity import (
    _SEARCH_URL,
    SCSOSBusinessSearch,
    _normalize_entity_name,
)


def test_standalone_fetch_is_a_no_op():
    """This module is an enrichment helper with zero real callers (see
    module docstring), not a board source -- fetch() must stay a no-op."""
    rows = asyncio.run(SCSOSBusinessSearch().fetch())
    assert rows == []


def test_scraper_is_disabled_so_safe_run_reports_dormant_not_zero():
    """FOUND batch 18: this class never set disabled=True despite
    auto-registering into the normal orchestration cycle -- every run was
    recording the ambiguous OUTCOME_ZERO instead of OUTCOME_DORMANT on a
    permanently CAPTCHA-walled, uncalled helper."""
    assert SCSOSBusinessSearch.disabled is True
    assert SCSOSBusinessSearch.disabled_reason


def test_search_url_is_the_known_dead_endpoint():
    """Confirmed live 2026-10-01: this exact path 404s. The site's real
    current flow is businessfilings.sc.gov -> Entity/ExistingFiling ->
    Entity/Search, which is itself reCAPTCHA-gated (a real g-recaptcha with
    a live data-sitekey appeared on the results page after submitting a
    search) -- a wall this codebase does not solve or route around. This is
    a documentation regression guard, not a network call: if this constant
    ever changes, the docstring's findings should be re-verified live."""
    assert _SEARCH_URL == "https://businessfilings.sc.gov/BusinessFiling/Web/Reporting/SearchByName"


def test_search_entity_short_name_returns_none_without_a_network_call():
    """A name under 3 chars after suffix-stripping is rejected before any
    request is made -- confirms the early-exit guard still works."""
    result = asyncio.run(SCSOSBusinessSearch.search_entity("A LLC"))
    assert result is None


def test_entity_suffix_normalization():
    assert _normalize_entity_name("Smith Properties, LLC") == "Smith Properties"
    assert _normalize_entity_name("Acme Corp.") == "Acme"
    assert _normalize_entity_name("Jones Holdings Inc") == "Jones Holdings"
    assert _normalize_entity_name("Independent Investments") == "Independent Investments"
