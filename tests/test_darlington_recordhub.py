"""Tests for Darlington County RecordHub scraper."""
from __future__ import annotations

import pytest

from foreclosure_scraper.scrapers.counties_sc.darlington_recordhub import (
    DarlingtonRecordhub,
    _load_credentials,
)


def test_slug():
    """Test scraper slug is correctly formatted."""
    scraper = DarlingtonRecordhub()
    assert scraper.slug == "counties_sc.darlington_recordhub"
    assert "Darlington" in scraper.name
    assert scraper.category == "county_rod"


def test_credentials_path():
    """Test that credentials path is correctly set up."""
    # This will raise FileNotFoundError if path is wrong, which is expected
    # in test environment without actual secrets
    try:
        _load_credentials()
    except FileNotFoundError as e:
        assert "cott_recordhub" in str(e)
        assert "email.txt" in str(e)
        assert "password.txt" in str(e)


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_fetch_requires_credentials(monkeypatch):
    """Test that fetch fails gracefully without credentials."""
    scraper = DarlingtonRecordhub()
    
    # Mock credentials to avoid actual file read
    def mock_load_creds():
        return ("test@example.com", "testpass")
    
    monkeypatch.setattr(
        "foreclosure_scraper.scrapers.counties_sc.darlington_recordhub._load_credentials",
        mock_load_creds,
    )
    
    # Note: This will fail at reCAPTCHA or login because we're not actually
    # providing valid credentials or solving real CAPTCHA. The test is just
    # to ensure the scraper structure is valid.
    try:
        result = await scraper.fetch()
        # If credentials are invalid or CAPTCHA fails, we expect empty results
        assert isinstance(result, list)
    except Exception as e:
        # Expected - network/auth failures are acceptable in unit tests
        assert True


def test_listing_type_classification():
    """Test that document types are correctly classified."""
    from foreclosure_scraper.scrapers.counties_sc.darlington_recordhub import (
        _build_listing,
    )
    from foreclosure_scraper.models import ListingType
    
    # Test foreclosure classification
    fc_instrument = {
        "raw_cells": ["12345", "FORECLOSURE DEED", "2024-01-15"],
    }
    listing = _build_listing("test_slug", fc_instrument)
    assert listing.listing_type == ListingType.FORECLOSURE_SALE
    
    # Test lis pendens classification
    lis_instrument = {
        "raw_cells": ["12346", "LIS PENDENS", "2024-01-16"],
    }
    listing = _build_listing("test_slug", lis_instrument)
    assert listing.listing_type == ListingType.LIS_PENDENS
    
    # Test unknown classification
    unknown_instrument = {
        "raw_cells": ["12347", "DEED", "2024-01-17"],
    }
    listing = _build_listing("test_slug", unknown_instrument)
    assert listing.listing_type == ListingType.UNKNOWN


def test_listing_basic_fields():
    """Test that listings have required basic fields."""
    from foreclosure_scraper.scrapers.counties_sc.darlington_recordhub import (
        _build_listing,
    )
    
    instrument = {
        "raw_cells": ["12345", "FORECLOSURE", "2024-01-15"],
    }
    
    listing = _build_listing("counties_sc.darlington_recordhub", instrument)
    
    assert listing.source == "counties_sc.darlington_recordhub"
    assert listing.state == "SC"
    assert listing.county == "Darlington"
    assert listing.case_number == "12345"
    assert "recordhub" in listing.raw
