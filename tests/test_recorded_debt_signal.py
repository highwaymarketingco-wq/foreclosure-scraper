"""recorded_debt must be a REAL debt, and scoring and equity must agree on what that is.

Audit 2026-09-21: distress_score counted any amount_owed.value as a FINANCIAL signal, including
the estimates enrichment_amount_owed labels "not debt" (assessed value, an assumed two years of
tax). 16,142 of 33,259 signals (49%) were estimates, and 644 of the 1,646 HOT leads were a
generic demolition-permit tag plus one such estimate.
"""
from __future__ import annotations

from foreclosure_scraper.distress_score import _signals_for
from foreclosure_scraper.enrichment_equity import is_countable_debt
from foreclosure_scraper.models import Listing, ListingType


def _lead(ao, lt=ListingType.DISTRESSED):
    return Listing(source="counties_nc.new_hanover_demolition_permits", source_url="u", listing_type=lt,
                   state="NC", county="New Hanover", raw={"amount_owed": ao} if ao is not None else {})


def _has_debt_signal(li):
    return any(n == "recorded_debt" for n, _c, _w in _signals_for(li))


def test_estimates_are_not_debt():
    assert not is_countable_debt({"value": 250000, "source": "assessed_value", "is_actual_debt": False})
    assert not is_countable_debt({"value": 906, "source": "estimated_tax_2yr", "confidence": "low", "is_actual_debt": False})
    assert not is_countable_debt({"value": 120000, "source": "sqft_based_estimate", "is_actual_debt": False})


def test_real_debts_count():
    assert is_countable_debt({"value": 187425, "source": "judgment", "is_actual_debt": True})
    assert is_countable_debt({"value": 9800, "source": "tax_owed", "is_actual_debt": True})


def test_a_foreclosure_opening_bid_counts_even_when_flagged_a_proxy():
    # the lender opens at ~the payoff; equity has always treated it as the debt
    assert is_countable_debt({"value": 143000, "source": "opening_bid", "is_actual_debt": False})


def test_empty_or_missing_is_not_debt():
    assert not is_countable_debt(None) and not is_countable_debt({}) and not is_countable_debt({"value": 0, "is_actual_debt": True})
    assert not is_countable_debt("garbage")


def test_scorer_ignores_an_estimated_debt():
    est = _lead({"value": 250000, "source": "assessed_value", "is_actual_debt": False})
    assert not _has_debt_signal(est)
    cats = {c for _n, c, _w in _signals_for(est)}
    assert "FINANCIAL" not in cats                       # a demolition-permit tag alone is one PROPERTY category


def test_scorer_counts_a_real_debt():
    real = _lead({"value": 187425, "source": "judgment", "is_actual_debt": True})
    assert _has_debt_signal(real)


def test_a_generic_permit_plus_an_estimate_can_no_longer_stack_to_two():
    li = _lead({"value": 250000, "source": "assessed_value", "is_actual_debt": False})
    assert len({c for _n, c, _w in _signals_for(li)}) <= 1


def _lead2(ao, tax_owed):
    raw = {}
    if ao is not None:
        raw["amount_owed"] = ao
    if tax_owed is not None:
        raw["tax_owed"] = tax_owed
    return Listing(source="counties_nc.new_hanover_demolition_permits", source_url="u",
                   listing_type=ListingType.DISTRESSED, state="NC", county="New Hanover", raw=raw)


def test_a_real_delinquent_tax_balance_counts_even_when_amount_owed_is_an_estimate():
    # the real New Hanover case: amount_owed picked an estimate over the real balance beside it
    li = _lead2({"value": 1574, "source": "estimated_tax_2yr", "is_actual_debt": False},
                {"balance": 110.44, "kind": "delinquent_tax", "year": 2025})
    assert _has_debt_signal(li)


def test_a_real_tax_balance_counts_with_no_amount_owed_at_all():
    assert _has_debt_signal(_lead2(None, {"balance": 5200.0, "kind": "delinquent_tax"}))


def test_a_zero_or_missing_tax_balance_does_not_count():
    assert not _has_debt_signal(_lead2({"value": 900, "source": "estimated_tax_2yr", "is_actual_debt": False}, {"balance": 0}))
    assert not _has_debt_signal(_lead2({"value": 900, "source": "estimated_tax_2yr", "is_actual_debt": False}, {"kind": "delinquent_tax"}))
    assert not _has_debt_signal(_lead2({"value": 900, "source": "estimated_tax_2yr", "is_actual_debt": False}, "garbage"))
