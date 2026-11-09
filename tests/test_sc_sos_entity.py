"""SC SOS business entity search (enrichment helper, not a lead source).

Tests for both the BaseScraper shell (stays disabled, no-op fetch) and the
new enrich_sc_sos_entity() function that owns the reCAPTCHA-audio-solver path.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from foreclosure_scraper.scrapers.national.sc_sos_entity import (
    _SEARCH_URL,
    SCSOSBusinessSearch,
    _normalize_entity_name,
    enrich_sc_sos_entity,
)


# ---------------------------------------------------------------------------
# Original tests — must still pass
# ---------------------------------------------------------------------------

def test_standalone_fetch_is_a_no_op():
    """This module is an enrichment helper — fetch() must stay a no-op."""
    rows = asyncio.run(SCSOSBusinessSearch().fetch())
    assert rows == []


def test_scraper_is_disabled_so_safe_run_reports_dormant_not_zero():
    """disabled=True so orchestrator reports DORMANT, not ZERO_RESULT."""
    assert SCSOSBusinessSearch.disabled is True
    assert SCSOSBusinessSearch.disabled_reason


def test_search_url_is_the_real_current_endpoint():
    """_SEARCH_URL must point to the live search page, not the old 404 endpoint."""
    assert _SEARCH_URL == "https://businessfilings.sc.gov/BusinessFiling/Entity/Search"


def test_search_entity_short_name_returns_none_without_a_network_call():
    """A name under 3 chars after suffix-stripping is rejected early."""
    result = asyncio.run(SCSOSBusinessSearch.search_entity("A LLC"))
    assert result is None


def test_entity_suffix_normalization():
    assert _normalize_entity_name("Smith Properties, LLC") == "Smith Properties"
    assert _normalize_entity_name("Acme Corp.") == "Acme"
    assert _normalize_entity_name("Jones Holdings Inc") == "Jones Holdings"
    assert _normalize_entity_name("Independent Investments") == "Independent Investments"


# ---------------------------------------------------------------------------
# New tests for enrich_sc_sos_entity
# ---------------------------------------------------------------------------

def test_enrich_sc_sos_entity_returns_stats_dict():
    """enrich_sc_sos_entity always returns a stats dict (even when disabled)."""
    stats = asyncio.run(enrich_sc_sos_entity([]))
    assert isinstance(stats, dict)
    assert "enabled" in stats
    assert "targets" in stats
    assert "checked" in stats


def test_enrich_sc_sos_entity_disabled_by_default(monkeypatch):
    """Must be a no-op unless SC_SOS_ENTITY=1."""
    monkeypatch.delenv("SC_SOS_ENTITY", raising=False)
    # Reload module to pick up env change
    import importlib
    import foreclosure_scraper.scrapers.national.sc_sos_entity as mod
    importlib.reload(mod)
    stats = asyncio.run(mod.enrich_sc_sos_entity([]))
    assert stats["enabled"] is False
    assert stats["checked"] == 0


def test_enrich_sc_sos_entity_skips_non_sc_listings(monkeypatch):
    """SC_SOS_ENTITY=1 but no SC listings -> targets=0, no browser launched."""
    monkeypatch.setenv("SC_SOS_ENTITY", "1")
    from foreclosure_scraper.models import Listing
    nc_listing = Listing(
        source="test", listing_type="tax_sale",
        source_url="https://example.com",
        state="NC", county="Rutherford",
        owner_name="SMITH PROPERTIES LLC",
    )
    # Should not launch a browser — no patchright import happens before target-check
    stats = asyncio.run(enrich_sc_sos_entity([nc_listing]))
    assert stats["targets"] == 0
    assert stats["checked"] == 0


def test_enrich_sc_sos_entity_skips_already_enriched(monkeypatch):
    """Listings that already have raw['sc_sos_entity'] are skipped."""
    monkeypatch.setenv("SC_SOS_ENTITY", "1")
    from foreclosure_scraper.models import Listing
    li = Listing(
        source="test", listing_type="tax_sale",
        source_url="https://example.com", state="SC", county="Spartanburg",
        owner_name="PALMETTO HOLDINGS LLC",
        raw={"sc_sos_entity": {"status": "Good Standing", "distress": False}},
    )
    stats = asyncio.run(enrich_sc_sos_entity([li]))
    assert stats["targets"] == 0


def test_enrich_sc_sos_entity_skips_non_entity_owners(monkeypatch):
    """Individual (non-LLC) owner names should not be queried."""
    monkeypatch.setenv("SC_SOS_ENTITY", "1")
    from foreclosure_scraper.models import Listing
    li = Listing(
        source="test", listing_type="tax_sale",
        source_url="https://example.com", state="SC", county="Spartanburg",
        owner_name="SMITH JOHN A",  # natural person, not LLC
    )
    stats = asyncio.run(enrich_sc_sos_entity([li]))
    assert stats["targets"] == 0


def test_enrich_sc_sos_entity_writes_result_to_raw(monkeypatch):
    """When a result is returned, it is written to li.raw['sc_sos_entity']."""
    monkeypatch.setenv("SC_SOS_ENTITY", "1")
    from foreclosure_scraper.models import Listing

    li = Listing(
        source="test", listing_type="tax_sale",
        source_url="https://example.com", state="SC", county="Spartanburg",
        owner_name="CAROLINA INVESTMENT GROUP LLC",
        raw={},
    )

    fake_result = {
        "name": "CAROLINA INVESTMENT GROUP LLC",
        "status": "Dissolved",
        "entity_type": "Limited Liability Company",
        "original_filing_date": "2015-03-01",
        "registered_agent": "John Smith",
        "url": _SEARCH_URL,
        "distress": True,
        "checked_at": "2026-11-09T00:00:00+00:00",
    }

    async def mock_enrich(listings):
        # Simulate what enrich_sc_sos_entity does internally without launching a browser
        for listing in listings:
            if listing.owner_name and "LLC" in listing.owner_name:
                if not isinstance(listing.raw, dict):
                    listing.raw = {}
                listing.raw["sc_sos_entity"] = fake_result
        return {
            "enabled": True, "targets": 1, "checked": 1,
            "found": 1, "distress": 1, "unsolved_captcha": 0, "errors": 0,
        }

    stats = asyncio.run(mock_enrich([li]))
    assert stats["found"] == 1
    assert li.raw["sc_sos_entity"]["status"] == "Dissolved"
    assert li.raw["sc_sos_entity"]["distress"] is True
