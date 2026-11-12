"""Pin the sale_date-based upset-bid window enrichment.

Critical investor signal — NCGS §45-21.27 + §45-21.26 give a ~14-day
operational window from sale_date during which any party can file an
upset bid. Before this enrichment, the only upset-bid logic was the NC
eCourts scraper's ordered_date-based tagging, which doesn't fire because
Tyler Odyssey's judgment-search index lags 30+ days behind actual
filings. enrichment_upset_bid works off the sale_date set by law-firm,
county-tax, and auction-site scrapers — sources that DO surface
recent-sale data.

Coupled with main._active_only's state-aware past cutoff (now 14 days
for NC + SC instead of 2), these listings now survive the filter chain
where they used to get silently dropped.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.enrichment_upset_bid import (
    UPSET_BID_WINDOW_DAYS,
    enrich_upset_bid,
)
from foreclosure_scraper.main import _active_only
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, days_since_sale: int | None, state: str = "NC", source: str = "law_firms.hutchens",
        **kw) -> Listing:
    if days_since_sale is None:
        sd = None
    else:
        sd = datetime.utcnow() - timedelta(days=days_since_sale)
    base = dict(
        source=source,
        source_url=f"https://example.com/{state}/{days_since_sale}",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county="Wake" if state == "NC" else "Spartanburg",
        sale_date=sd,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---- enrich_upset_bid behavior ----

def test_window_constant_is_14_days():
    """NC §45-21.27's 10-day-from-report-filing + §45-21.26's 5-day filing
    deadline = ~14 day operational window from sale_date."""
    assert UPSET_BID_WINDOW_DAYS == 14


def test_recent_sale_tagged_in_window():
    """Sale 3 days ago → in window with 11 days remaining."""
    li = _li(days_since_sale=3)
    enrich_upset_bid([li])
    ub = li.raw["upset_bid"]
    assert ub["in_window"] is True
    assert ub["days_remaining"] == 11
    assert ub["sale_occurred_on_iso"]
    assert ub["statute"] == "NCGS §45-21.27"
    assert li.upset_bid_deadline is not None


def test_sale_today_full_window_remaining():
    li = _li(days_since_sale=0)
    enrich_upset_bid([li])
    assert li.raw["upset_bid"]["in_window"] is True
    assert li.raw["upset_bid"]["days_remaining"] == 14


def test_sale_at_boundary_still_in_window():
    """14 days ago = exactly at boundary, inclusive."""
    li = _li(days_since_sale=14)
    enrich_upset_bid([li])
    assert li.raw["upset_bid"]["in_window"] is True
    assert li.raw["upset_bid"]["days_remaining"] == 0


def test_sale_15_days_ago_outside_window():
    li = _li(days_since_sale=15)
    enrich_upset_bid([li])
    assert "upset_bid" not in li.raw
    assert li.upset_bid_deadline is None


def test_future_sale_not_tagged():
    """Sale scheduled 5 days in future — not yet sold, not in window."""
    sd = datetime.utcnow() + timedelta(days=5)
    li = _li(days_since_sale=None, source="law_firms.hutchens")
    li.sale_date = sd
    enrich_upset_bid([li])
    assert "upset_bid" not in li.raw


def test_no_sale_date_skipped():
    li = _li(days_since_sale=None)
    li.sale_date = None
    stats = enrich_upset_bid([li])
    assert stats["no_sale_date"] == 1
    assert "upset_bid" not in li.raw


def test_non_nc_listing_not_tagged():
    """SC has its own (different) confirmation window — this enrichment
    is NC-specific."""
    li = _li(days_since_sale=3, state="SC")
    enrich_upset_bid([li])
    assert "upset_bid" not in li.raw


# ---- confidence scoring ----

def test_law_firm_source_high_confidence():
    """Law-firm trustees actually conduct the sale → HIGH confidence."""
    li = _li(days_since_sale=2, source="law_firms.brock_scott")
    enrich_upset_bid([li])
    assert li.raw["upset_bid"]["confidence"] == "HIGH"


def test_master_in_equity_high_confidence():
    li = _li(days_since_sale=2, source="counties_sc.spartanburg_master_in_equity")
    li.state = "NC"  # force tagging
    enrich_upset_bid([li])
    assert li.raw["upset_bid"]["confidence"] == "HIGH"


def test_county_tax_medium_confidence():
    li = _li(days_since_sale=2, source="counties_nc.forsyth_tax")
    enrich_upset_bid([li])
    assert li.raw["upset_bid"]["confidence"] == "MEDIUM"


# ---- stale-flag clearing ----

def test_stale_in_window_flag_cleared_when_sale_now_old():
    """A listing previously tagged in_window (e.g. by NC eCourts at scrape
    time) but whose sale_date is now >14 days ago must have its flag
    cleared so dashboards don't show stale upset-bid windows."""
    li = _li(days_since_sale=20)
    li.raw["upset_bid"] = {"in_window": True, "days_remaining": 5}
    li.upset_bid_deadline = datetime.utcnow() + timedelta(days=5)
    enrich_upset_bid([li])
    # Flag cleared, deadline cleared
    assert li.raw["upset_bid"]["in_window"] is False
    assert li.raw["upset_bid"]["stale_reason"]
    assert li.upset_bid_deadline is None


# ---- _active_only integration: NC sales 0-14 days past survive ----

def test_active_only_keeps_nc_sale_3_days_past():
    """The Run-#16-era 2-day past cutoff dropped these. Now they survive."""
    li = _li(days_since_sale=3, state="NC")
    assert _active_only(li, horizon_days=120) is True


def test_active_only_keeps_nc_sale_10_days_past():
    li = _li(days_since_sale=10, state="NC")
    assert _active_only(li, horizon_days=120) is True


def test_active_only_drops_nc_sale_15_days_past():
    """Past the upset-bid window — drop."""
    li = _li(days_since_sale=15, state="NC")
    assert _active_only(li, horizon_days=120) is False


def test_active_only_keeps_sc_sale_within_grace():
    """SC also gets the 14-day grace (for parity / future SC upset
    analog work)."""
    li = _li(days_since_sale=10, state="SC")
    assert _active_only(li, horizon_days=120) is True


# ---- end-to-end: most-actionable signal flows through ----

def test_real_scenario_three_law_firm_listings_get_tagged():
    """Simulates the 3 listings observed in Run #16: law-firm trustee
    listings sold in past 0-1 days. All should get in_window=True with
    HIGH confidence and a deadline 14 days from sale."""
    listings = [
        _li(days_since_sale=0, source="law_firms.brock_scott"),
        _li(days_since_sale=0, source="national.auction_dot_com"),
        _li(days_since_sale=1, source="law_firms.hutchens"),
    ]
    stats = enrich_upset_bid(listings)
    assert stats["tagged_in_window"] == 3
    for li in listings:
        ub = li.raw["upset_bid"]
        assert ub["in_window"] is True
        assert li.upset_bid_deadline is not None
