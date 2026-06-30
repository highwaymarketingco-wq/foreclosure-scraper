"""Upstate-SC obituaries: slug->name parsing + registry auto-discovery."""
from foreclosure_scraper.scrapers.counties_sc.upstate_obituaries import (
    _name_from_slug, UpstateObituaries,
)


def test_name_from_slug_basic():
    assert _name_from_slug("jefferson-trawick-austin") == "Jefferson Trawick Austin"
    assert _name_from_slug("deborah-mccallister") == "Deborah Mccallister"


def test_name_from_slug_suffix_and_initial():
    assert _name_from_slug("harry-a-chapman-jr") == "Harry A Chapman Jr."
    assert _name_from_slug("john-f-farr-jr") == "John F Farr Jr."


def test_covers_three_core_counties():
    from foreclosure_scraper.scrapers.counties_sc.upstate_obituaries import PAPERS
    assert set(PAPERS.values()) == {"Spartanburg", "Greenville", "Anderson"}


def test_registry_auto_discovers_it():
    from foreclosure_scraper.scrapers._registry import discover
    assert any(c is UpstateObituaries for c in discover())
