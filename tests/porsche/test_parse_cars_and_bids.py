"""Cars & Bids HTML parser — fixture-based test.

C&B retired its public JSON endpoint; the search page is now a SPA
that we render and parse `li.auction-item` cards out of.
"""
from __future__ import annotations

from pathlib import Path

from porsche_scraper.filters import FilterCriteria, filter_listings
from porsche_scraper.models import TitleStatus
from porsche_scraper.scrapers.cars_and_bids import parse_search_html

FIXTURE = Path(__file__).parent / "fixtures" / "cars_and_bids.html"


def test_parses_all_three_auction_cards():
    """All three cards parse. Cayenne is no longer dropped at parse time
    (model exclusion lifted 2026-05-13, commit 1e9e158)."""
    listings = parse_search_html(FIXTURE.read_text())
    assert len(listings) == 3
    slugs = {l.source_url for l in listings}
    assert any("2014-porsche-boxster-base" in s for s in slugs)
    assert any("2018-porsche-911-rebuilt" in s for s in slugs)
    assert any("cayenne" in s.lower() for s in slugs)


def test_title_status_inference():
    listings = parse_search_html(FIXTURE.read_text())
    by_title = {l.title: l for l in listings}
    rebuilt = next(l for l in listings if "911" in l.title)
    assert rebuilt.title_status == TitleStatus.REBUILT
    boxster = next(l for l in listings if "Boxster" in l.title)
    assert boxster.title_status == TitleStatus.CLEAN


def test_strips_ss_id_tracking_param_from_url():
    listings = parse_search_html(FIXTURE.read_text())
    for l in listings:
        assert "ss_id" not in l.source_url
        assert "?" not in l.source_url


def test_extracts_bid_and_mileage():
    listings = parse_search_html(FIXTURE.read_text())
    boxster = next(l for l in listings if "Boxster" in l.title)
    assert boxster.current_bid_usd == 22500.0
    assert boxster.mileage == 58000


def test_filter_keeps_cayenne_and_rebuilt_911_at_high_price():
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=45_000)
    kept = filter_listings(parse_search_html(FIXTURE.read_text()), crit)
    kept_titles = {l.title for l in kept}
    assert any("Boxster" in t for t in kept_titles)   # $22.5k clean — under cap.
    assert any("Cayenne" in t for t in kept_titles)   # $25k clean — under cap, now in-scope.
    assert any("911" in t for t in kept_titles)       # $55k but rebuilt-title exception.
