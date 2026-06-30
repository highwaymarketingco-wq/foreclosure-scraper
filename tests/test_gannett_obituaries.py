"""Gannett obituaries: slug->name parsing + footprint + registry discovery."""
from foreclosure_scraper.scrapers.public_notices.gannett_obituaries import (
    _name_from_slug, GannettObituaries, PAPERS,
)


def test_name_basic_suffix_initial():
    assert _name_from_slug("jefferson-trawick-austin") == "Jefferson Trawick Austin"
    assert _name_from_slug("harry-a-chapman-jr") == "Harry A Chapman Jr."


def test_name_strips_trailing_disambiguator():
    assert _name_from_slug("sara-moore-2026-1") == "Sara Moore"
    assert _name_from_slug("glenn-stepp") == "Glenn Stepp"


def test_covers_core_wnc_and_upstate_counties():
    counties = {c for c, _ in PAPERS.values()}
    # Western NC core
    assert {"Buncombe", "Henderson", "Gaston", "Cleveland", "Rutherford"} <= counties
    # Upstate SC core
    assert {"Spartanburg", "Greenville", "Anderson"} <= counties
    states = {s for _, s in PAPERS.values()}
    assert states == {"NC", "SC"}


def test_registry_auto_discovers_it():
    from foreclosure_scraper.scrapers._registry import discover
    assert any(c is GannettObituaries for c in discover())
