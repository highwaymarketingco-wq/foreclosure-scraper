"""Pin the NC case-status heuristic enrichment.

The Tyler-portal-based sold-price extraction was retired (AWS WAF
blocks all non-browser traffic to portal-nc.tylertech.cloud). The
replacement is a sale-date heuristic + Trustee's Deed Upon Sale
cross-reference against the post-sale ROD pool.

Tests pin the date-bucket cutoffs (NCGS §45-21.27 + filing-slack) and
the deed-match override path.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.enrichment_nc_case_status import (
    UPSET_BID_DAYS,
    _build_trustee_deed_index,
    _norm_addr_key,
    _status_from_sale_date,
    enrich_with_nc_case_status,
)
from foreclosure_scraper.models import Listing, ListingType


NOW = datetime(2026, 5, 8, 12, 0, 0)


def _li(**kw) -> Listing:
    base = dict(
        source="counties_nc.test",
        source_url="https://example.com/test",
        state="NC",
        listing_type=ListingType.LIS_PENDENS,
    )
    base.update(kw)
    return Listing(**base)


# ---- _status_from_sale_date date buckets ----

def test_future_sale_date_returns_scheduled():
    sd = NOW + timedelta(days=14)
    out = _status_from_sale_date(sd, NOW)
    assert out["status"] == "scheduled"
    assert out["in_upset_bid_window"] is False


def test_sale_today_in_upset_bid_window():
    out = _status_from_sale_date(NOW, NOW)
    assert out["status"] == "upset_bid"
    assert out["in_upset_bid_window"] is True
    assert out["days_since_sale"] == 0


def test_sale_5_days_ago_in_upset_bid_window():
    out = _status_from_sale_date(NOW - timedelta(days=5), NOW)
    assert out["status"] == "upset_bid"
    assert out["in_upset_bid_window"] is True


def test_sale_at_exactly_upset_cutoff_in_window():
    """Day 14 is the inclusive cutoff (statute says 10 + 4 days slack)."""
    out = _status_from_sale_date(NOW - timedelta(days=UPSET_BID_DAYS), NOW)
    assert out["status"] == "upset_bid"
    assert out["in_upset_bid_window"] is True


def test_sale_one_day_after_cutoff_pending_confirmation():
    out = _status_from_sale_date(NOW - timedelta(days=UPSET_BID_DAYS + 1), NOW)
    assert out["status"] == "pending_confirmation"
    assert out["in_upset_bid_window"] is False


def test_sale_25_days_ago_pending_confirmation():
    out = _status_from_sale_date(NOW - timedelta(days=25), NOW)
    assert out["status"] == "pending_confirmation"


def test_sale_45_days_ago_confirmed():
    """Past 30 days with no deed = treated as confirmed."""
    out = _status_from_sale_date(NOW - timedelta(days=45), NOW)
    assert out["status"] == "confirmed"
    assert out["in_upset_bid_window"] is False


def test_no_sale_date_returns_none():
    assert _status_from_sale_date(None, NOW) is None


# ---- _norm_addr_key cross-reference key ----

def test_norm_addr_key_combines_street_zip():
    li = _li(street_address="123 Main St", zip_code="28801")
    assert _norm_addr_key(li) == "123 MAIN ST|28801"


def test_norm_addr_key_uppercases_street():
    li = _li(street_address="456 elm ave", zip_code="28704")
    assert _norm_addr_key(li) == "456 ELM AVE|28704"


def test_norm_addr_key_truncates_zip_plus4():
    li = _li(street_address="789 Oak", zip_code="28801-1234")
    assert _norm_addr_key(li) == "789 OAK|28801"


def test_norm_addr_key_returns_none_without_zip():
    li = _li(street_address="123 Main St")
    assert _norm_addr_key(li) is None


def test_norm_addr_key_returns_none_without_street():
    li = _li(zip_code="28801")
    assert _norm_addr_key(li) is None


# ---- _build_trustee_deed_index ----

def test_deed_index_picks_up_recordings_with_actual_sold_price():
    deed = _li(
        street_address="100 Pine Rd",
        zip_code="28704",
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=NOW - timedelta(days=20),
        raw={"actual_sold_price": 125000.0},
    )
    idx = _build_trustee_deed_index([deed])
    assert "100 PINE RD|28704" in idx


def test_deed_index_skips_listings_without_actual_sold_price():
    no_price = _li(
        street_address="100 Pine Rd",
        zip_code="28704",
        listing_type=ListingType.FORECLOSURE_SALE,
        raw={},
    )
    idx = _build_trustee_deed_index([no_price])
    assert idx == {}


def test_deed_index_keeps_most_recent_when_duplicates():
    older = _li(
        street_address="100 Pine Rd",
        zip_code="28704",
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=NOW - timedelta(days=60),
        raw={"actual_sold_price": 100000.0},
    )
    newer = _li(
        street_address="100 Pine Rd",
        zip_code="28704",
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=NOW - timedelta(days=10),
        raw={"actual_sold_price": 125000.0},
    )
    idx = _build_trustee_deed_index([older, newer])
    assert idx["100 PINE RD|28704"].raw["actual_sold_price"] == 125000.0


# ---- enrich_with_nc_case_status integration ----

def test_enrich_skips_non_nc_listings():
    sc_li = _li(state="SC", sale_date=NOW - timedelta(days=5))
    enrich_with_nc_case_status([sc_li])
    assert (sc_li.raw or {}).get("nc_case_status") is None


def test_enrich_skips_bankruptcy_source():
    li = _li(
        source="national.courtlistener_bankruptcy",
        sale_date=NOW - timedelta(days=5),
    )
    enrich_with_nc_case_status([li])
    assert (li.raw or {}).get("nc_case_status") is None


def test_enrich_tags_active_nc_listing_with_status():
    li = _li(
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=datetime.utcnow() - timedelta(days=3),
    )
    enrich_with_nc_case_status([li])
    info = (li.raw or {}).get("nc_case_status")
    assert info is not None
    assert info["status"] == "upset_bid"
    assert info["in_upset_bid_window"] is True


def test_enrich_with_trustee_deed_overrides_to_confirmed():
    """Active listing has sale_date 5 days ago (would be upset_bid by
    pure-date heuristic), but a recorded Trustee's Deed exists at the
    same address — so status flips to confirmed via deed-match."""
    active = _li(
        street_address="200 Oak St",
        zip_code="28805",
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=datetime.utcnow() - timedelta(days=5),
    )
    deed = _li(
        street_address="200 Oak St",
        zip_code="28805",
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=datetime.utcnow() - timedelta(days=3),
        raw={"actual_sold_price": 175000.0},
    )
    enrich_with_nc_case_status([active], sold_pool=[deed])
    info = active.raw["nc_case_status"]
    assert info["status"] == "confirmed"
    assert info["method"] == "trustee_deed_match"
    assert info["in_upset_bid_window"] is False
    assert info["trustee_deed_price"] == 175000.0


def test_enrich_listing_without_sale_date_skipped():
    li = _li(listing_type=ListingType.FORECLOSURE_SALE, sale_date=None)
    enrich_with_nc_case_status([li])
    assert (li.raw or {}).get("nc_case_status") is None


def test_enrich_handles_empty_sold_pool():
    li = _li(
        listing_type=ListingType.FORECLOSURE_SALE,
        sale_date=datetime.utcnow() - timedelta(days=20),
    )
    enrich_with_nc_case_status([li], sold_pool=[])
    info = li.raw["nc_case_status"]
    assert info["status"] == "pending_confirmation"
    assert info["method"] == "sale_date_heuristic"


def test_upset_bid_deadline_is_iso_date():
    sd = datetime(2026, 5, 1)
    out = _status_from_sale_date(sd, datetime(2026, 5, 8))
    assert out["upset_bid_deadline"] == "2026-05-15"
