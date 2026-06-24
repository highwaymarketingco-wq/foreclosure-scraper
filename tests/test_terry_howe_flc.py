"""Terry Howe FLC parser — county filter + FLC address extraction."""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc import terry_howe_flc as th


def test_county_of_keeps_in_footprint_sc():
    assert th._county_of("Spartanburg County, SC – 8 Properties for FLC") == "Spartanburg"
    assert th._county_of("Laurens County, SC – 6 Properties") == "Laurens"


def test_county_of_drops_out_of_footprint():
    # Fairfield is not in the SC footprint; a city-only title has no county.
    assert th._county_of("Fairfield County, SC – 6 Properties") is None
    assert th._county_of("Rock Hill, SC – 4 BR home") is None


def test_clean_addresses_strips_item_number_and_drops_off_locators():
    body = ("00 817 Saxon Ave 01 567 Farley Ave 02 Off Dodd St "
            "03 4 Buckthorn Rd 04 342 Ridgewood Ave 05 Off Crescent Ave")
    got = th._clean_addresses(body)
    assert "817 Saxon Ave" in got
    assert "567 Farley Ave" in got
    assert "4 Buckthorn Rd" in got
    assert "342 Ridgewood Ave" in got
    # vague "Off X" locators (no house number) are dropped
    assert not any("off" in a.lower() for a in got)


def test_clean_addresses_dedups():
    body = "00 817 Saxon Ave 09 817 Saxon Ave"
    assert th._clean_addresses(body) == ["817 Saxon Ave"]
