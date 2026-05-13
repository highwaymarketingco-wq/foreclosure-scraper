"""Cars.com parser — fixture-based test."""
from __future__ import annotations

from pathlib import Path

from porsche_scraper.filters import FilterCriteria, filter_listings
from porsche_scraper.models import TitleStatus
from porsche_scraper.scrapers.cars_com import parse_results_html

FIXTURE = Path(__file__).parent / "fixtures" / "cars_com_results.html"


def test_parses_all_jsonld_vehicles():
    listings = parse_results_html(FIXTURE.read_text())
    urls = {l.source_url for l in listings}
    # 4 JSON-LD items present; HTML fallback shouldn't trigger.
    assert len(listings) == 4
    assert any("cayman-s-charlotte" in u for u in urls)
    assert any("2018-porsche-macan" in u for u in urls)
    assert any("2017-porsche-911-rebuilt" in u for u in urls)


def test_jsonld_fields_populated_correctly():
    listings = parse_results_html(FIXTURE.read_text())
    cayman = next(l for l in listings if "cayman-s-charlotte" in l.source_url)
    assert cayman.year == 2016
    assert cayman.model == "Cayman"
    assert cayman.price_usd == 39_995.0
    assert cayman.mileage == 62_150
    assert cayman.vin == "WP0AB2A86GK170111"
    assert cayman.source == "cars_com"


def test_rebuilt_detected_from_title():
    listings = parse_results_html(FIXTURE.read_text())
    rebuilt = next(l for l in listings if "rebuilt" in l.source_url)
    assert rebuilt.title_status == TitleStatus.REBUILT


def test_user_criteria_keeps_cayman_drops_macan_keeps_rebuilt_911():
    listings = parse_results_html(FIXTURE.read_text())
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=45_000)
    kept = filter_listings(listings, crit)
    titles = {l.title for l in kept}
    assert "2016 Porsche Cayman S" in titles
    assert "2015 Porsche Boxster" in titles
    # Rebuilt 911 over $45k is kept (rebuilt-title exception).
    assert "2017 Porsche 911 Carrera - rebuilt title" in titles
    # Macan excluded.
    assert not any("Macan" in t for t in titles)
