"""Regression tests for the NC eCourts upset-bid window constant.

NC §45-21.27 strict reading is 10 days from filing of the report of
sale; §45-21.26 gives the trustee 5 days from sale to file the report.
Practical operational window measured from sale_date is up to 15 days.
We use 14 as the operational threshold investors typically work with.

Note: the AUTHORITATIVE upset-bid tagging now happens in
enrichment_upset_bid.py (works off li.sale_date, which is the sale
date set by law-firm / county-tax / auction-site scrapers). The NC
eCourts scraper's ordered_date-based tagging is preserved as a
secondary signal but doesn't fire reliably because the Tyler Odyssey
judgment search has a multi-week indexer lag (current data shows 0-30
day bucket = 0 listings; everything is 31+ days old).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    TARGET_COUNTIES,
    UPSET_BID_WINDOW_DAYS,
    _hit_to_listing,
)


def _hit(ordered_date_iso: str, **extras) -> dict:
    base = {
        "causeOfActionDesc": "CV - Lis Pendens",
        "caseNumber": "26M001234-590",
        "orderedDate": ordered_date_iso,
        "judgmentType": "Civil Judgment",
        "location": "Wake District Court",
        "debtors": [{"name": "Smith, John"}],
        "creditors": [{"name": "Bank of NC"}],
    }
    base.update(extras)
    return base


def test_upset_bid_window_constant():
    # 14 days from sale_date is the operational threshold (NCGS §45-21.27
    # gives 10 days from report-filing; §45-21.26 gives 5 days from sale
    # to file the report; total practical window is ~14-15 days from sale).
    assert UPSET_BID_WINDOW_DAYS == 14


def test_target_counties_match_user_territory():
    """Current scope: WNC mountains/foothills only. Eastern-NC + Charlotte
    (Mecklenburg) + Madison/Yancey were pruned 2026-05-07, and the coastal
    trio (New Hanover/Brunswick/Onslow) was pruned 2026-05-15 ("anything
    east of Charlotte"). TARGET_COUNTIES is now derived from
    config.NC_COUNTIES so it tracks scope automatically."""
    # User-key NC counties in scope:
    for c in ("Buncombe", "Henderson", "Gaston", "Cleveland",
              "Rutherford", "Polk", "Transylvania", "McDowell",
              "Lincoln", "Mitchell", "Burke"):
        assert c in TARGET_COUNTIES, f"{c} missing from TARGET_COUNTIES"
    # Counties dropped from scope:
    for c in ("Wake", "Forsyth", "Guilford", "Durham", "Cumberland",
              "Mecklenburg", "Madison", "Yancey",
              "New Hanover", "Brunswick", "Onslow"):
        assert c not in TARGET_COUNTIES, (
            f"{c} should have been removed from TARGET_COUNTIES"
        )


def test_recent_sale_flagged_in_upset_bid_window():
    """A sale ordered 3 days ago is within the 14-day window."""
    od = (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li is not None
    assert li.upset_bid_deadline is not None
    ub = li.raw.get("upset_bid") or {}
    assert ub["in_window"] is True
    assert ub["days_remaining"] == 11  # 14 - 3
    assert ub["statute"] == "NCGS §45-21.27"


def test_old_sale_not_flagged():
    """A sale ordered 30 days ago is OUTSIDE the upset bid window."""
    od = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li is not None
    assert li.upset_bid_deadline is None
    assert "upset_bid" not in (li.raw or {})


def test_sale_at_window_boundary():
    """Exactly 14 days ago — still in window per the inclusive bound."""
    od = (datetime.utcnow() - timedelta(days=14)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li.upset_bid_deadline is not None
    ub = li.raw.get("upset_bid") or {}
    assert ub["days_remaining"] == 0


def test_no_ordered_date_no_flag():
    """Listing without orderedDate cannot be classified — no flag."""
    li = _hit_to_listing(_hit(""), "test")
    # Either filtered out or no upset_bid block
    if li is not None:
        assert li.upset_bid_deadline is None
        assert "upset_bid" not in (li.raw or {})
