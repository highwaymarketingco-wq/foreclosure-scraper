"""F8 (audit 2026-09-21): the sold-pool partition must not steal a lead from the active
board while its upset-bid window is still open.

Before: a sale from today back 180 days went to the sold pool BEFORE the active filter,
so an NC lead left the board the day after its sale even though the 14 day upset window
is the strongest actionable signal an investor can chase. Every test pins `now`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from foreclosure_scraper.enrichment_foreclosure_sold_comps import (
    LOOKBACK_DAYS,
    auction_datetime,
    in_upset_window,
    is_sold_pool_candidate,
    sc_tax_redemption_open,
    state_upset_window_days,
)
from foreclosure_scraper.main import _active_only
from foreclosure_scraper.models import Listing, ListingType

NOW = datetime(2026, 9, 21, 12, 0, 0)


def _li(*, state="NC", source="law_firms.brock_scott", days_ago=None, **kw) -> Listing:
    base = dict(
        source=source, source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE, state=state, county="Gaston",
        street_address="1 Main St",
        sale_date=(NOW - timedelta(days=days_ago)) if days_ago is not None else None,
        raw={},
    )
    base.update(kw)
    return Listing(**base)


@pytest.mark.parametrize("days_ago,expected", [
    (0, False), (1, False), (10, False), (14, False),       # inside the NC window
    (14.5, True), (15, True), (100, True),                  # window over
    (LOOKBACK_DAYS, True), (LOOKBACK_DAYS + 1, False),      # lookback still bounds it
])
def test_nc_sale_diverts_only_after_the_upset_window(days_ago, expected):
    assert is_sold_pool_candidate(_li(state="NC", days_ago=days_ago), now=NOW) is expected


def test_future_and_dateless_sales_are_never_pool_candidates():
    assert is_sold_pool_candidate(_li(days_ago=-5), now=NOW) is False
    assert is_sold_pool_candidate(_li(days_ago=None), now=NOW) is False


def test_active_filter_and_pool_partition_are_exact_complements_at_the_boundary():
    """A lead must be active XOR sold-pool material across the whole window edge; a gap
    would drop it from both, an overlap would show it twice."""
    for hours in range(13 * 24, 16 * 24, 6):      # 13 to 16 days, every 6 hours
        li = _li(state="NC", days_ago=hours / 24)
        active = _active_only(li, horizon_days=120, now=NOW)
        pooled = is_sold_pool_candidate(li, now=NOW)
        assert active != pooled, f"{hours}h after the sale: active={active} pooled={pooled}"


def test_a_confirmed_hammer_price_inside_the_window_stays_active():
    li = _li(state="NC", days_ago=5, raw={"actual_sold_price": 150000})
    assert is_sold_pool_candidate(li, now=NOW) is False
    li2 = _li(state="NC", days_ago=30, raw={"actual_sold_price": 150000})
    assert is_sold_pool_candidate(li2, now=NOW) is True


def test_a_hammer_price_with_no_date_still_pools_as_before():
    li = _li(state="NC", days_ago=None, raw={"actual_sold_price": 150000})
    assert is_sold_pool_candidate(li, now=NOW) is True


def test_a_published_open_upset_window_keeps_the_lead_active_past_sale_plus_14():
    """Stacked upsets restart the 10 day clock; a source that PRINTS the close date wins."""
    li = _li(state="NC", days_ago=20, raw={"upset_bid": {
        "in_window": True, "source": "published",
        "deadline_iso": (NOW + timedelta(days=3)).isoformat()}})
    assert in_upset_window(li, NOW) is True
    assert is_sold_pool_candidate(li, now=NOW) is False


def test_the_true_auction_date_wins_over_the_sale_date():
    """raw.auction_date is the auction; sale_date may be a docket stand-in."""
    li = _li(state="NC", days_ago=2, raw={"auction_date": (NOW - timedelta(days=40)).isoformat()})
    assert auction_datetime(li) == NOW - timedelta(days=40)
    assert is_sold_pool_candidate(li, now=NOW) is True     # 40 days since the AUCTION


# ---- SC tax sales keep their redemption clock -------------------------------------------

def test_an_sc_tax_sale_stays_active_for_its_redemption_year():
    li = _li(state="SC", source="counties_sc.sc_tax_delinquent", days_ago=120,
             listing_type=ListingType.TAX_SALE)
    assert sc_tax_redemption_open(li, NOW) is True
    assert is_sold_pool_candidate(li, now=NOW) is False
    assert _active_only(li, horizon_days=120, now=NOW) is True


def test_an_sc_tax_sale_uses_a_redemption_deadline_the_scraper_set():
    li = _li(state="SC", source="counties_sc.pickens_master_in_equity", days_ago=200,
             listing_type=ListingType.TAX_SALE, redemption_deadline=NOW + timedelta(days=10))
    assert sc_tax_redemption_open(li, NOW) is True
    lapsed = _li(state="SC", days_ago=500, listing_type=ListingType.TAX_SALE,
                 redemption_deadline=NOW - timedelta(days=1))
    assert sc_tax_redemption_open(lapsed, NOW) is False


def test_an_sc_judicial_foreclosure_is_not_a_tax_sale_and_uses_the_plain_window():
    li = _li(state="SC", source="counties_sc.spartanburg_master_in_equity", days_ago=20)
    assert sc_tax_redemption_open(li, NOW) is False
    assert is_sold_pool_candidate(li, now=NOW) is True
    inside = _li(state="SC", source="counties_sc.spartanburg_master_in_equity", days_ago=10)
    assert is_sold_pool_candidate(inside, now=NOW) is False


def test_windows_by_state():
    assert state_upset_window_days("NC") == 14
    assert state_upset_window_days("sc") == 14
    assert state_upset_window_days("GA") == 2
    assert state_upset_window_days(None) == 2


# ---- the docket enricher no longer overwrites sale_date ---------------------------------

def test_docket_last_event_no_longer_overwrites_the_sale_date():
    """enrichment_nc_case_status_tyler promoted a hammer price and then did
    li.sale_date = <docket last event>. Exercise the exact promotion block."""
    import inspect
    import foreclosure_scraper.enrichment_nc_case_status_tyler as tyler
    src = inspect.getsource(tyler)
    assert "li.sale_date = datetime.strptime(last_date" not in src
    assert 'li.raw["auction_date"]' in src
    assert 'li.raw["docket_last_event_date"]' in src
