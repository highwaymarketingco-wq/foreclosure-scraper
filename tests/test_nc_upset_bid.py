"""Regression tests for the NC eCourts upset-bid window detection.

NC General Statutes §45-21.27: any party may file an upset bid within
10 calendar days of the trustee sale, raising the high bid by ≥5%
plus statutory interest. A property still in this window is the most
actionable foreclosure type for an investor — comp the property,
finance the bid, file before the deadline.
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
    assert UPSET_BID_WINDOW_DAYS == 10


def test_target_counties_includes_high_volume_metros():
    """Audit added Wake, Forsyth, Guilford, Durham, Cumberland, New
    Hanover for foreclosure-volume coverage."""
    for c in ("Wake", "Forsyth", "Guilford", "Durham", "Cumberland", "New Hanover"):
        assert c in TARGET_COUNTIES, f"{c} missing from TARGET_COUNTIES"
    # Original WNC counties still present
    for c in ("Mecklenburg", "Buncombe", "Henderson"):
        assert c in TARGET_COUNTIES


def test_recent_sale_flagged_in_upset_bid_window():
    """A sale ordered 3 days ago is within the 10-day window."""
    od = (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li is not None
    assert li.upset_bid_deadline is not None
    ub = li.raw.get("upset_bid") or {}
    assert ub["in_window"] is True
    assert ub["days_remaining"] == 7  # 10 - 3
    assert ub["statute"] == "NCGS §45-21.27"


def test_old_sale_not_flagged():
    """A sale ordered 30 days ago is OUTSIDE the upset bid window."""
    od = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li is not None
    assert li.upset_bid_deadline is None
    assert "upset_bid" not in (li.raw or {})


def test_sale_at_window_boundary():
    """Exactly 10 days ago — still in window per the inclusive bound."""
    od = (datetime.utcnow() - timedelta(days=10)).isoformat() + "Z"
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
