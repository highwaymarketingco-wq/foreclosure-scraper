"""Tests for the NC Register-of-Deeds substitute-trustee scraper.

Live testing requires Scrapling stealth + a real browser context (not
available in CI). These tests pin the portal configuration and the
RENDER-REQUIRED classification so the source is registered correctly
even before the per-vendor stealth flows are wired.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc.nc_rod_substitute_trustee import (
    COUNTY_PORTALS,
    NCRodSubstituteTrustee,
)


def test_covers_buncombe_only_after_scope_rollback():
    """2026-05-07b scope rollback: Mecklenburg + Wake + Durham portals
    deactivated when those counties were dropped from NC_COUNTIES.
    Only Buncombe remains in scope. Original portals are preserved
    as code comments for fast re-activation."""
    expected = {"Buncombe"}
    assert set(COUNTY_PORTALS) == expected


def test_each_portal_has_required_config():
    for county, cfg in COUNTY_PORTALS.items():
        assert cfg["url"].startswith("https://"), f"{county} URL not https"
        assert cfg["doc_types"], f"{county} has no doc_types"
        # Substitute trustee deed is the highest-value doc type;
        # every county must include it.
        assert any("SUBSTITUTE TRUSTEE" in dt for dt in cfg["doc_types"])
        assert cfg["vendor"] in {"manatron", "aumentum", "permitium"}


def test_scraper_class_metadata():
    s = NCRodSubstituteTrustee()
    assert s.slug == "counties_nc.nc_rod_substitute_trustee"
    assert s.expected_min_count == 0
    assert getattr(s, "requires_render", False) is True


def test_skeleton_returns_empty_without_stealth_wired():
    """Until per-vendor Scrapling flows land, the scraper returns []
    cleanly so the run summary shows RENDER-REQUIRED, not error/regress."""
    s = NCRodSubstituteTrustee()
    out = list(asyncio.run(s.fetch()))
    assert out == []
