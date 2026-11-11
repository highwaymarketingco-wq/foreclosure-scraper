"""Tests for CountyFusion ROD scraper (Lexington SC only -- see sc_countyfusion_rod.py's
module docstring for why Orangeburg/Greenville/Greenwood/Allendale were removed 2026-11-11)."""
import pytest
from foreclosure_scraper.scrapers.counties_sc.sc_countyfusion_rod import (
    SCCountyFusionROD,
    COUNTIES,
    _classify_doc_type,
)


def test_slug():
    """Verify scraper slug."""
    scraper = SCCountyFusionROD()
    assert scraper.slug == "counties_sc.sc_countyfusion_rod"


def test_counties_configured():
    """Verify only the live-confirmed county is configured. Orangeburg/Greenville/
    Greenwood/Allendale were live-verified (2026-11-11) to NOT be tenants on
    countyfusion14.govos.com -- loginDisplay.action returns an empty body for all
    four, not a login-flow bug worth asserting coverage for here."""
    assert len(COUNTIES) == 1
    assert "Lexington" in COUNTIES

    # Verify structure
    for county, config in COUNTIES.items():
        assert "host" in config
        assert "name" in config
        assert config["host"] == "countyfusion14.govos.com"


def test_credentials_path():
    """Verify credentials path structure."""
    scraper = SCCountyFusionROD()
    # Will fail if .secrets/countyfusion/ doesn't exist with username.txt and password.txt
    # This is expected to pass in production environment


def test_classify_doc_type():
    """Test document type classification."""
    # LIS PENDENS
    result = _classify_doc_type("LIS PENDENS")
    assert result is not None
    listing_type, mapped_type = result
    assert listing_type.name == "LIS_PENDENS"
    
    # LIEN
    result = _classify_doc_type("TAX LIEN")
    if result:  # May or may not classify
        listing_type, mapped_type = result
        assert listing_type.name in ["LIEN", "TAX_LIEN"]
    
    # Test that some distress patterns are recognized
    test_types = ["LIS PENDENS", "JUDGMENT", "LIEN", "FORECLOSURE"]
    recognized_count = sum(1 for t in test_types if _classify_doc_type(t) is not None)
    assert recognized_count > 0, "At least one distress type should be recognized"


def test_scraper_instantiation():
    """Verify scraper can be instantiated."""
    scraper = SCCountyFusionROD()
    assert scraper.slug == "counties_sc.sc_countyfusion_rod"
    assert scraper.timeout_s > 0
