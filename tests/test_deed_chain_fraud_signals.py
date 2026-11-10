"""enrich_fraud_signals: cross-references raw['deed_chain'] against raw['heir_candidates'] and the
recorded date of death to flag a conveyance that looks like fraud against an heir (DPA
master_sources_and_signals.md item B.20: forged deeds / fake POA / impersonation at closing).
Every parcel, owner and address here is made up."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from foreclosure_scraper.enrichment_deed_chain import enrich_fraud_signals
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

NOW = datetime(2026, 11, 10)
DOD = date(2026, 1, 1)


def _li(raw=None, market_value=None):
    return Listing(source="s", source_url="https://x.invalid/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state="NC", county="Sample",
                   parcel_id="1357-24-6801", street_address="11 Test Rd", owner_name="ALPHA ANN",
                   latitude=35.111, longitude=-81.222, first_seen=NOW, last_seen=NOW,
                   market_value=market_value, raw=raw or {})


def _death_raw(**extra):
    """A minimal sc_probate_notice block -- the cheapest path through death_fact() to a
    date_of_death without needing has_real_probate()'s stricter 'probate' key gate."""
    raw = {"sc_probate_notice": {"case_number": "25ES000111", "date_of_death": DOD.isoformat()}}
    raw.update(extra)
    return raw


def test_transfer_30_days_after_death_is_near_death_true():
    transfer_date = (DOD + timedelta(days=30)).isoformat()
    li = _li(raw=_death_raw(deed_chain={"transfers": [
        {"date": transfer_date, "price": 90000.0, "grantor": "ALPHA ANN", "grantee": "BETA BOB"},
    ], "summary": {}}))
    enrich_fraud_signals([li])
    sig = li.raw["fraud_signals"]
    assert sig["near_death_transfer"] is True
    assert sig["details"]["near_death_transfer"]["days"] == 30


def test_transfer_200_days_after_death_is_near_death_false():
    transfer_date = (DOD + timedelta(days=200)).isoformat()
    li = _li(raw=_death_raw(deed_chain={"transfers": [
        {"date": transfer_date, "price": 90000.0, "grantor": "ALPHA ANN", "grantee": "BETA BOB"},
    ], "summary": {}}))
    enrich_fraud_signals([li])
    sig = li.raw["fraud_signals"]
    assert sig["near_death_transfer"] is False
    assert "near_death_transfer" not in sig["details"]


def test_two_heirs_one_sole_grantor_is_co_heir_cutout_true():
    li = _li(raw={
        "heir_candidates": [
            {"name": "JOHN DOE", "relation": "son"},
            {"name": "MARY DOE", "relation": "daughter"},
        ],
        "deed_chain": {"transfers": [
            {"date": "2024-06-01", "price": 95000.0, "grantor": "JOHN DOE", "grantee": "OUTSIDE LLC"},
        ], "summary": {}},
    })
    enrich_fraud_signals([li])
    sig = li.raw["fraud_signals"]
    assert sig["co_heir_cutout"] is True
    assert sig["details"]["co_heir_cutout"]["heir_name"] == "JOHN DOE"
    assert sig["details"]["co_heir_cutout"]["heir_count"] == 2
    # the uninvolved facts stay false -- no death date and a full-price transfer
    assert sig["near_death_transfer"] is False
    assert sig["undervalued_transfer"] is False


def test_both_heirs_as_joint_grantors_is_not_a_cutout():
    """Both co-heirs conveying together is an ordinary joint sale, not a targeted cutout --
    'exactly 1' grantor match is required, so a joint deed (both match) must NOT flag."""
    li = _li(raw={
        "heir_candidates": [
            {"name": "JOHN DOE", "relation": "son"},
            {"name": "MARY DOE", "relation": "daughter"},
        ],
        "deed_chain": {"transfers": [
            {"date": "2024-06-01", "price": 95000.0, "grantor": "JOHN DOE AND MARY DOE",
             "grantee": "OUTSIDE LLC"},
        ], "summary": {}},
    })
    enrich_fraud_signals([li])
    assert li.raw["fraud_signals"]["co_heir_cutout"] is False


def test_price_at_40pct_of_assessed_value_is_undervalued_true():
    li = _li(market_value=100000.0, raw={"deed_chain": {"transfers": [
        {"date": "2024-06-01", "price": 40000.0, "grantor": "ALPHA ANN", "grantee": "BETA BOB"},
    ], "summary": {}}})
    enrich_fraud_signals([li])
    sig = li.raw["fraud_signals"]
    assert sig["undervalued_transfer"] is True
    assert sig["details"]["undervalued_transfer"]["price"] == 40000.0
    assert sig["details"]["undervalued_transfer"]["assessed_value"] == 100000.0
    assert sig["details"]["undervalued_transfer"]["ratio"] == 0.4


def test_love_and_affection_price_is_not_double_counted_as_undervalued():
    """$1/$0/$10/$100 nominal prices are the existing, stricter _LOVE_AND_AFFECTION check --
    this broader 50%-of-assessed-value signal must not also fire on the same transfer."""
    li = _li(market_value=100000.0, raw={"deed_chain": {"transfers": [
        {"date": "2024-06-01", "price": 1.0, "grantor": "ALPHA ANN", "grantee": "BETA BOB"},
    ], "summary": {}}})
    enrich_fraud_signals([li])
    assert li.raw["fraud_signals"]["undervalued_transfer"] is False


def test_clean_row_is_all_false():
    li = _li(market_value=100000.0, raw={"deed_chain": {"transfers": [
        {"date": "2024-06-01", "price": 90000.0, "grantor": "ALPHA ANN", "grantee": "BETA BOB"},
    ], "summary": {}}})
    enrich_fraud_signals([li])
    assert li.raw["fraud_signals"] == {
        "near_death_transfer": False,
        "co_heir_cutout": False,
        "undervalued_transfer": False,
        "details": {},
    }


def test_no_deed_chain_is_not_stamped_at_all():
    """No chain to cross-reference means nothing to say -- matches enrich_deed_chain's own rule
    of only stamping rows that have real chain data, rather than writing a vacuous all-False
    block onto every row on the board that has no deed chain at all."""
    li = _li(raw={"heir_candidates": [{"name": "JOHN DOE", "relation": "son"}]})
    stats = enrich_fraud_signals([li])
    assert "fraud_signals" not in li.raw
    assert stats["stamped"] == 0
