"""Pin _flip_candidate behavior (H2 fix).

Before H2 fix, _flip_candidate had a missing return statement at the
end of the most common branch (bid in [1, 750_000] for SFR/condo/
townhouse). Python returned None (falsy), silently dropping every
priced-SFR ≤ $750k listing — the user's primary investment target.

These tests pin each branch so the bug can't quietly come back.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.main import _flip_candidate
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw) -> Listing:
    base = dict(
        source="test",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


# ---- KEEP branches ----

def test_no_bid_kept():
    """Bid unknown → keep (don't drop blindly)."""
    li = _li(opening_bid=None)
    assert _flip_candidate(li) is True


def test_zero_bid_kept():
    """Zero/null bid → keep (treated as unknown)."""
    li = _li(opening_bid=0)
    assert _flip_candidate(li) is True


def test_sfr_under_750k_kept():
    """H2 motivating case: SFR with bid in [1, 750_000] is the
    primary flip target. Pre-fix, this returned None and got dropped."""
    li = _li(opening_bid=200_000, property_kind=PropertyKind.SINGLE_FAMILY)
    result = _flip_candidate(li)
    assert result is True, f"Expected True for SFR @ $200k, got {result!r}"


def test_condo_under_750k_kept():
    li = _li(opening_bid=150_000, property_kind=PropertyKind.CONDO)
    assert _flip_candidate(li) is True


def test_townhouse_under_750k_kept():
    li = _li(opening_bid=300_000, property_kind=PropertyKind.TOWNHOUSE)
    assert _flip_candidate(li) is True


def test_sfr_at_750k_kept():
    """Exact 750k boundary — should keep (the > check is strict)."""
    li = _li(opening_bid=750_000, property_kind=PropertyKind.SINGLE_FAMILY)
    assert _flip_candidate(li) is True


def test_multifamily_high_price_kept():
    """Multi-family bypasses the $750k cap (apartment complex valuation
    works differently)."""
    li = _li(opening_bid=2_000_000, property_kind=PropertyKind.MULTI_FAMILY)
    # Note: still dropped if > $1.5M HARD cap fires first
    # The function: $1.5M check happens BEFORE the MF bypass, so $2M MF is dropped
    assert _flip_candidate(li) is False


def test_multifamily_under_1_5m_kept():
    """Multi-family under hard cap → keep regardless of $750k threshold."""
    li = _li(opening_bid=1_200_000, property_kind=PropertyKind.MULTI_FAMILY)
    assert _flip_candidate(li) is True


def test_land_high_price_kept():
    """Land bypasses $750k cap (priced by acreage, not building size)."""
    li = _li(opening_bid=1_000_000, property_kind=PropertyKind.LAND)
    assert _flip_candidate(li) is True


def test_sfr_over_750k_with_acreage_kept():
    """SFR >$750k with 2+ acres → keep (acreage justifies price)."""
    li = _li(
        opening_bid=900_000,
        property_kind=PropertyKind.SINGLE_FAMILY,
        lot_size_sqft=3 * 43_560,  # 3 acres
    )
    assert _flip_candidate(li) is True


# ---- DROP branches ----

def test_hard_cap_above_1_5m_dropped():
    li = _li(opening_bid=2_000_000, property_kind=PropertyKind.SINGLE_FAMILY)
    assert _flip_candidate(li) is False


def test_sfr_over_750k_without_acreage_dropped():
    """SFR $900k on <2 acres → drop (super-luxury, not our scope)."""
    li = _li(
        opening_bid=900_000,
        property_kind=PropertyKind.SINGLE_FAMILY,
        lot_size_sqft=20_000,  # 0.5 acres
    )
    assert _flip_candidate(li) is False


def test_sfr_over_750k_without_lot_size_dropped():
    """No lot_size_sqft on $900k SFR → can't justify, drop."""
    li = _li(
        opening_bid=900_000,
        property_kind=PropertyKind.SINGLE_FAMILY,
        lot_size_sqft=None,
    )
    assert _flip_candidate(li) is False


# ---- never-return-None guarantee ----

def test_function_always_returns_bool_not_none():
    """Belt-and-suspenders: across every reasonable input, the result
    must be True or False, never None. If anyone reintroduces a
    missing-return branch, this test fails."""
    test_cases = [
        _li(opening_bid=None),
        _li(opening_bid=0),
        _li(opening_bid=1),
        _li(opening_bid=50_000, property_kind=PropertyKind.SINGLE_FAMILY),
        _li(opening_bid=500_000, property_kind=PropertyKind.CONDO),
        _li(opening_bid=750_000, property_kind=PropertyKind.TOWNHOUSE),
        _li(opening_bid=1_000_000, property_kind=PropertyKind.SINGLE_FAMILY),
        _li(opening_bid=1_500_000, property_kind=PropertyKind.MULTI_FAMILY),
        _li(opening_bid=2_000_000, property_kind=PropertyKind.LAND),
        _li(opening_bid=100_000, property_kind=PropertyKind.UNKNOWN),
    ]
    for li in test_cases:
        result = _flip_candidate(li)
        assert result in (True, False), (
            f"_flip_candidate returned {result!r} (not bool) for "
            f"bid={li.opening_bid} kind={li.property_kind}"
        )
