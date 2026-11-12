"""The board must not accumulate sold cars. prune_sold_and_stale keeps it current.

Before this, the daily merge only ever ADDED listings — so Copart/IAA lots and
Bring-a-Trailer results from months (even years) back stayed on the dashboard
forever. The operator saw "sold ones from May". These pin the two rules that
fix it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from porsche_scraper.models import Listing
from scripts.import_sf_csv import prune_sold_and_stale


def _l(source, url, sale_date=None) -> Listing:
    return Listing(source=source, source_url=url, title="2016 Porsche Cayman",
                   year=2016, sale_date=sale_date)


def test_drops_past_auctions():
    past = datetime.now(timezone.utc) - timedelta(days=40)
    future = datetime.now(timezone.utc) + timedelta(days=5)
    board = [
        _l("copart", "https://x/1", sale_date=past),    # auction already happened
        _l("copart", "https://x/2", sale_date=future),  # still upcoming
        _l("cars_com", "https://x/3"),                  # no sale_date (dealer)
    ]
    kept = prune_sold_and_stale(board, fresh=[])
    urls = {l.source_url for l in kept}
    assert "https://x/1" not in urls   # past auction dropped
    assert "https://x/2" in urls
    assert "https://x/3" in urls


def test_drops_fell_off_a_rescraped_source():
    # `listings` arrives already deduped, so the merged board is 5 unique cars.
    board = [_l("carvana", f"https://c/{i}") for i in range(5)]
    # This run re-scraped carvana and found only 0,1,2 — 3 and 4 are gone.
    fresh = [_l("carvana", f"https://c/{i}") for i in range(3)]
    kept = prune_sold_and_stale(board, fresh=fresh)
    urls = {l.source_url for l in kept}
    assert urls == {"https://c/0", "https://c/1", "https://c/2"}


def test_leaves_unscraped_sources_untouched():
    # A source with no fresh rows this run must NOT be wiped — absence of data
    # is not evidence the cars are gone.
    board = [_l("truecar", f"https://t/{i}") for i in range(5)]
    fresh = [_l("carvana", "https://c/0"), _l("carvana", "https://c/1"),
             _l("carvana", "https://c/2")]
    kept = prune_sold_and_stale(board + fresh, fresh=fresh)
    assert len([l for l in kept if l.source == "truecar"]) == 5


def test_a_blocked_run_does_not_wipe_a_source():
    # Only 2 fresh rows from carvana (below the min) — treat as unreliable and
    # leave the existing carvana entries alone rather than delete most of them.
    board = [_l("carvana", f"https://c/{i}") for i in range(8)]
    fresh = [_l("carvana", "https://c/0"), _l("carvana", "https://c/1")]
    kept = prune_sold_and_stale(board, fresh=fresh)
    assert len([l for l in kept if l.source == "carvana"]) == 8
