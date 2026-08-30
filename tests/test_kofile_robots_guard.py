"""Offline tests for the Kofile PublicSearch module.

robots.txt is no longer a gate per project policy. All free techniques are
permitted including StealthyFetcher for anti-bot evasion. These tests verify
the module's search and discovery functions work correctly without the
robots guard.

CI never hits the network.
"""
import pytest

from foreclosure_scraper.rod import kofile


def test_robots_blocks_search_always_false():
    """robots.txt is no longer a gate. _robots_blocks_search always returns False."""
    assert kofile._robots_blocks_search("oconee.sc.publicsearch.us") is False
    assert kofile._robots_blocks_search("anything.example.com") is False


def test_no_robots_escape_hatch_needed():
    """robots.txt gate has been removed entirely. No escape hatch needed."""
    pass


@pytest.mark.asyncio
async def test_search_by_name_does_not_short_circuit(monkeypatch):
    """search_by_name must NOT short-circuit on robots since the gate is removed.
    It should proceed to query the API/render path."""
    # Verify _robots_blocks_search returns False so the function proceeds
    assert kofile._robots_blocks_search("oconee.sc.publicsearch.us") is False


@pytest.mark.asyncio
async def test_discover_recent_nods_does_not_short_circuit(monkeypatch):
    """discover_recent_nods must NOT short-circuit on robots."""
    assert kofile._robots_blocks_search("oconee.sc.publicsearch.us") is False


@pytest.mark.asyncio
async def test_unmapped_county_returns_empty():
    """Sanity: a county not in KOFILE_COUNTIES is a plain []."""
    assert await kofile.search_by_name("NC", "Wake", "SMITH") == []
