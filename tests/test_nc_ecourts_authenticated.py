"""Pin the authenticated NC eCourts (Tyler) scraper's pure logic.

The browser-driven login + case-search flow is integration-only (needs
real credentials + the live Tyler portal). These tests exercise the
parsers, regex extractors, and dispatch logic — everything that doesn't
need a network.
"""
from __future__ import annotations

import os

import pytest

from foreclosure_scraper.enrichment_nc_case_status_tyler import (
    SOLD_PRICE_PATTERNS,
    _extract_sold_price,
    _normalize_status,
    _parse_case_detail_html,
    _within_n_days,
    enrich_with_nc_case_status_authenticated,
)


# ---- _extract_sold_price ----

def test_high_bid_pattern_extracts():
    assert _extract_sold_price("Order Confirming Sale - high bid of $128,500.00 to ABC LLC") == 128500.0


def test_sold_for_pattern_extracts():
    assert _extract_sold_price("Sold for $32,000") == 32000.0


def test_purchase_price_pattern_extracts():
    assert _extract_sold_price("Confirmation - purchase price $250,000") == 250000.0


def test_implausibly_low_rejected():
    assert _extract_sold_price("Sold for $50.00") is None


def test_implausibly_high_rejected():
    assert _extract_sold_price("high bid of $50,000,000") is None


def test_empty_returns_none():
    assert _extract_sold_price("") is None
    assert _extract_sold_price(None) is None  # noqa


def test_at_least_six_patterns_defined():
    """Coverage breadth is what makes this work against Tyler's varied
    docket-entry phrasing — fail loud if anyone trims the list."""
    assert len(SOLD_PRICE_PATTERNS) >= 6


# ---- _normalize_status ----

def test_normalize_status_dismissed():
    assert _normalize_status("Case dismissed by court") == "dismissed"


def test_normalize_status_confirmed():
    assert _normalize_status("Order Confirming Sale entered") == "confirmed"


def test_normalize_status_upset_bid():
    assert _normalize_status("Upset bid filed by John Smith") == "upset_bid"


def test_normalize_status_sold():
    assert _normalize_status("Property sold at sheriff sale") == "sold"


def test_normalize_status_scheduled():
    assert _normalize_status("Sale pending, scheduled for March 15") == "scheduled"


def test_normalize_status_unknown_returns_none():
    assert _normalize_status("Random unrelated text without keywords") is None


def test_normalize_status_priority_dismissed_over_confirmed():
    """When both keywords appear, dismissed wins because the case is
    actually closed — Order Confirming Sale entries pre-dismissal would
    otherwise mis-tag a closed case as still active."""
    text = "Order Confirming Sale entered. Subsequently dismissed by court."
    assert _normalize_status(text) == "dismissed"


# ---- _within_n_days ----

def test_within_n_days_true_for_recent():
    """Date 5 days ago is within 14-day window."""
    from datetime import datetime, timedelta
    recent = (datetime.utcnow() - timedelta(days=5)).strftime("%m/%d/%Y")
    assert _within_n_days(recent, 14) is True


def test_within_n_days_false_for_old():
    """Date 30 days ago is NOT within 14-day window."""
    from datetime import datetime, timedelta
    old = (datetime.utcnow() - timedelta(days=30)).strftime("%m/%d/%Y")
    assert _within_n_days(old, 14) is False


def test_within_n_days_invalid_format_returns_false():
    assert _within_n_days("not-a-date", 14) is False


def test_within_n_days_2digit_year():
    from datetime import datetime, timedelta
    recent = (datetime.utcnow() - timedelta(days=3)).strftime("%m/%d/%y")
    assert _within_n_days(recent, 14) is True


# ---- _parse_case_detail_html ----

def test_parse_case_detail_picks_up_status():
    html = "<html><body>" + "x" * 1500 + " Order Confirming Sale entered " + "y" * 100 + "</body></html>"
    info = _parse_case_detail_html(html)
    assert info is not None
    assert info["status"] == "confirmed"
    assert info["method"] == "tyler_authenticated"


def test_parse_case_detail_extracts_sold_price_when_confirmed():
    html = (
        "<html><body>"
        + "x" * 1100
        + " Order Confirming Sale - high bid of $87,500.00 to Buyer LLC "
        + "y" * 200
        + "</body></html>"
    )
    info = _parse_case_detail_html(html)
    assert info["status"] == "confirmed"
    assert info["sold_price"] == 87500.0


def test_parse_case_detail_extracts_last_event():
    html = (
        "<html><body>"
        + "x" * 1100
        + " 03/15/2026 Order Confirming Sale entered "
        + "y" * 200
        + "</body></html>"
    )
    info = _parse_case_detail_html(html)
    assert info.get("last_event_date") == "03/15/2026"
    assert "confirming" in (info.get("last_event_text") or "").lower()


def test_parse_case_detail_returns_none_for_empty():
    assert _parse_case_detail_html("") is None


def test_parse_case_detail_returns_none_for_no_status():
    """Page without any status keywords should return None — we'd rather
    skip than tag with junk."""
    html = "<html><body>" + "lorem ipsum " * 200 + "</body></html>"
    assert _parse_case_detail_html(html) is None


# ---- dispatch behavior ----

@pytest.mark.asyncio
async def test_dispatch_no_creds_returns_zero(monkeypatch):
    """When NC_ECOURTS_USERNAME/PASSWORD are missing, function should
    log + return 0 without attempting browser launch."""
    monkeypatch.delenv("NC_ECOURTS_USERNAME", raising=False)
    monkeypatch.delenv("NC_ECOURTS_PASSWORD", raising=False)
    out = await enrich_with_nc_case_status_authenticated([])
    assert out == 0


@pytest.mark.asyncio
async def test_dispatch_no_targets_returns_zero(monkeypatch):
    """Empty listings list = 0 tagged, no browser launch."""
    monkeypatch.setenv("NC_ECOURTS_USERNAME", "test@example.com")
    monkeypatch.setenv("NC_ECOURTS_PASSWORD", "testpass")
    out = await enrich_with_nc_case_status_authenticated([])
    assert out == 0


@pytest.mark.asyncio
async def test_dispatch_skips_listings_without_case_number(monkeypatch):
    """Listings without case_number can't be queried — skip them all,
    return 0 (and don't attempt a browser launch)."""
    from foreclosure_scraper.models import Listing, ListingType
    monkeypatch.setenv("NC_ECOURTS_USERNAME", "test@example.com")
    monkeypatch.setenv("NC_ECOURTS_PASSWORD", "testpass")
    li = Listing(
        source="counties_nc.test",
        source_url="https://example.com",
        state="NC",
        listing_type=ListingType.LIS_PENDENS,
        case_number=None,
    )
    out = await enrich_with_nc_case_status_authenticated([li])
    assert out == 0


# ---- two-stage dispatch in enrichment_nc_case_status ----

@pytest.mark.asyncio
async def test_two_stage_dispatch_runs_heuristic_when_no_creds(monkeypatch):
    """No Tyler creds → heuristic still runs."""
    monkeypatch.delenv("NC_ECOURTS_USERNAME", raising=False)
    monkeypatch.delenv("NC_ECOURTS_PASSWORD", raising=False)
    from datetime import datetime, timedelta
    from foreclosure_scraper.enrichment_nc_case_status import (
        enrich_with_nc_case_status_dispatched,
    )
    from foreclosure_scraper.models import Listing, ListingType
    li = Listing(
        source="counties_nc.test",
        source_url="https://example.com",
        state="NC",
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=datetime.utcnow() - timedelta(days=5),
    )
    await enrich_with_nc_case_status_dispatched([li])
    info = li.raw["nc_case_status"]
    assert info["method"] == "sale_date_heuristic"
    assert info["status"] == "upset_bid"
