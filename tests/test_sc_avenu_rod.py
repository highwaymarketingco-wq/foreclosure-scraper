"""Tests for SC Avenu Insights ROD scraper."""
import pytest
from datetime import datetime
from foreclosure_scraper.scrapers.counties_sc.sc_avenu_rod import (
    _parse_avenu_date,
    _is_distress_instrument,
    _classify_listing,
    DISTRESS_INDICES,
)
from foreclosure_scraper.models import ListingType


def test_parse_avenu_date():
    """Test parsing Avenu's date formats."""
    # /Date(ms)/ format
    assert _parse_avenu_date("/Date(1700000000000)/") is not None
    
    # MM/DD/YYYY format
    result = _parse_avenu_date("11/11/2026")
    assert result is not None
    assert result.month == 11
    assert result.day == 11
    assert result.year == 2026
    
    # None/empty
    assert _parse_avenu_date(None) is None
    assert _parse_avenu_date("") is None


def test_is_distress_instrument():
    """Test distress instrument detection."""
    assert _is_distress_instrument("LIS PENDENS", None)
    assert _is_distress_instrument("FORECLOSURE DEED", None)
    assert _is_distress_instrument(None, "SHERIFF SALE")
    assert _is_distress_instrument("DEED", "TAX LIEN")
    assert not _is_distress_instrument("WARRANTY DEED", "SALE OF PROPERTY")
    assert not _is_distress_instrument(None, None)


def test_classify_listing():
    """Test listing classification logic."""
    assert _classify_listing("LIS PENDENS", None) == ListingType.LIS_PENDENS
    assert _classify_listing("FORECLOSURE DEED", None) == ListingType.FORECLOSURE_SALE
    assert _classify_listing("SHERIFF DEED", None) == ListingType.SHERIFF_SALE
    assert _classify_listing("TAX LIEN", None) == ListingType.TAX_LIEN
    assert _classify_listing("TAX SALE", "DEED") == ListingType.TAX_SALE
    assert _classify_listing("WARRANTY DEED", None) == ListingType.UNKNOWN


def test_distress_indices():
    """Test that distress index IDs are defined."""
    assert isinstance(DISTRESS_INDICES, dict)
    assert 1 in DISTRESS_INDICES  # DEED
    assert 2 in DISTRESS_INDICES  # MORTGAGE
    assert 4 in DISTRESS_INDICES  # JUDGEMENT
    assert 5 in DISTRESS_INDICES  # TAXLIEN


@pytest.mark.asyncio
async def test_scraper_instantiation():
    """Test that the scraper can be instantiated."""
    from foreclosure_scraper.scrapers.counties_sc.sc_avenu_rod import ScAvenuRod
    
    scraper = ScAvenuRod()
    assert scraper.slug == "counties_sc.sc_avenu_rod"
    assert scraper.name == "SC Avenu Insights ROD (Williamsburg, Kershaw, Newberry)"
    assert scraper.category == "county_rod"


# Note: Full integration tests require live credentials and are not included here
# Run those manually with: python -m foreclosure_scraper run counties_sc.sc_avenu_rod
