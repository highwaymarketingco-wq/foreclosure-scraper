"""Cars & Bids JSON parser — fixture-based test."""
from __future__ import annotations

import json
from pathlib import Path

from porsche_scraper.filters import FilterCriteria, filter_listings
from porsche_scraper.models import TitleStatus
from porsche_scraper.scrapers.cars_and_bids import parse_results

FIXTURE = Path(__file__).parent / "fixtures" / "cars_and_bids.json"


def test_parses_three_auctions():
    payload = json.loads(FIXTURE.read_text())
    listings = parse_results(payload)
    assert len(listings) == 3
    slugs = {l.source_url for l in listings}
    assert any("2014-porsche-boxster-base" in s for s in slugs)


def test_title_status_inference():
    payload = json.loads(FIXTURE.read_text())
    listings = parse_results(payload)
    by_model = {l.model: l for l in listings}
    assert by_model["911"].title_status == TitleStatus.REBUILT
    assert by_model["Boxster"].title_status == TitleStatus.CLEAN


def test_filter_drops_cayenne_keeps_rebuilt_911_at_high_price():
    payload = json.loads(FIXTURE.read_text())
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=45_000)
    kept = filter_listings(parse_results(payload), crit)
    kept_models = {l.model for l in kept}
    assert "Cayenne" not in kept_models  # Excluded.
    assert "Boxster" in kept_models  # Under price cap.
    assert "911" in kept_models  # Above cap but rebuilt-title exception.
