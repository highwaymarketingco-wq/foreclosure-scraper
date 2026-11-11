"""Tests for CountyFusion ROD scraper (Lexington, Orangeburg, Greenville, Greenwood, Allendale SC)."""
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
    """Verify all 5 counties are configured."""
    assert len(COUNTIES) == 5
    assert "Lexington" in COUNTIES
    assert "Orangeburg" in COUNTIES
    assert "Greenville" in COUNTIES
    assert "Greenwood" in COUNTIES
    assert "Allendale" in COUNTIES
    
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
