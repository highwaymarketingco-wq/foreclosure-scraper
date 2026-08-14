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


def test_parses_all_auction_cards():
    """Cayenne is now INCLUDED (feat 1e9e158); all three cards parse."""
    listings = parse_search_html(FIXTURE.read_text())
    assert len(listings) == 3
    slugs = {l.source_url for l in listings}
    assert any("2014-porsche-boxster-base" in s for s in slugs)
    assert any("2018-porsche-911-rebuilt" in s for s in slugs)
    assert any("2017-porsche-cayenne-platinum" in s for s in slugs)


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


def test_filter_keeps_under_cap_drops_rebuilt_911_over_cap():
    # New intent (2026-08-12): under $40k on every source, not just salvage.
    # Fixture bids: Boxster $22.5k, Cayenne $25k, rebuilt 911 $55k.
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=40_000)
    kept_titles = {l.title for l in
                   filter_listings(parse_search_html(FIXTURE.read_text()), crit)}
    assert any("Cayenne" in t for t in kept_titles)  # $25k, not an excluded model
    assert any("Boxster" in t for t in kept_titles)  # $22.5k
    # The rebuilt 911 bid is $55k — over the cap, so it is now dropped despite
    # the rebuilt title. Known price beats title on a bargain board.
    assert not any("911" in t for t in kept_titles)
