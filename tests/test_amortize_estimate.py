"""Tests for the labelled amortization estimate that turns a recorded ORIGINAL
principal into an ESTIMATED current balance for the equity engine.

The distinction under test is the legally important one: the recorded principal
is a public fact; the current balance is a model. A true payoff is borrower-only
under TILA/RESPA, so nothing here may ever be presented as one.
"""
from datetime import date

import pytest

from foreclosure_scraper.valuation.amortize import (
    _AVG_30YR,
    amortized_balance,
    estimate_current_balance,
    rate_for_month,
    rate_for_year,
)


# --- PMMS rate resolution ----------------------------------------------------
def test_annual_rate_comes_from_the_pmms_table():
    assert rate_for_year(2021) == _AVG_30YR[2021]
    assert rate_for_year(2022) == _AVG_30YR[2022]


def test_month_resolution_interpolates_between_annual_averages():
    """PMMS publishes an ANNUAL AVERAGE, so a January note sits closer to the
    prior year. 2022 went 3.0% -> 5.3% -> 6.8%, and a flat annual step misprices
    both ends of that year badly."""
    jan22, src = rate_for_month(2022, 1)
    assert src == "pmms_month_interpolated"
    assert _AVG_30YR[2021] < jan22 < _AVG_30YR[2022]
    dec22, _ = rate_for_month(2022, 12)
    assert _AVG_30YR[2022] < dec22 < _AVG_30YR[2023]


def test_midyear_month_equals_the_annual_average():
    july, src = rate_for_month(2019, 7)
    assert july == pytest.approx(_AVG_30YR[2019])
    assert src == "pmms_month_interpolated"


def test_month_falls_back_to_annual_at_the_table_edges():
    assert rate_for_month(2021, None) == (_AVG_30YR[2021], "pmms_annual")
    # 1999 is outside the table -> no interpolation, flagged as a default
    assert rate_for_month(1999, 6)[1] == "default"


def test_amortized_balance_uses_the_month_resolved_rate():
    """A note recorded in Jan-2022 amortizes at a rate between the 2021 and 2022
    annual averages, so its balance differs from the flat-annual answer."""
    monthly = amortized_balance(300000.0, date(2022, 1, 15), as_of=date(2026, 1, 15))
    flat = amortized_balance(300000.0, date(2022, 1, 15), rate=_AVG_30YR[2022],
                             as_of=date(2026, 1, 15))
    assert monthly is not None and flat is not None
    assert monthly != flat


# --- labelled estimate -------------------------------------------------------
def test_estimate_is_labelled_and_amortizes_down():
    est = estimate_current_balance(165000.0, "2019-04-12", as_of=date(2026, 8, 4))
    assert est is not None
    assert est["is_estimate"] is True
    assert est["method"] == "amortized_30yr_fixed"
    assert est["basis"] == "recorded_principal"
    assert est["original_principal"] == 165000.0
    assert 0 < est["estimated_balance"] < 165000.0
    assert est["months_paid"] == 88          # Apr-2019 -> Aug-2026
    assert est["rate_source"] == "pmms_month_interpolated"
    assert "payoff" in est["disclaimer"].lower()
    assert "TILA" in est["disclaimer"]


def test_confidence_is_never_high():
    """The model ignores escrow, arrears, ARMs, refis and extra payments, so it
    must never claim high confidence no matter how clean the inputs."""
    for when in ("2024-06-01", "2010-01-01", "1998-03-01"):
        est = estimate_current_balance(200000.0, when)
        assert est["confidence"] in ("medium", "low")


def test_recent_note_with_a_table_rate_is_medium():
    est = estimate_current_balance(200000.0, "2021-06-01", as_of=date(2026, 8, 4))
    assert est["confidence"] == "medium"


def test_old_note_degrades_to_low():
    """15+ years of assumed paydown has almost certainly been overtaken by a
    refi/HELOC/modification we cannot see."""
    est = estimate_current_balance(200000.0, "2006-06-01", as_of=date(2026, 8, 4))
    assert est["confidence"] == "low"


def test_rate_outside_the_pmms_table_degrades_to_low():
    est = estimate_current_balance(200000.0, "1996-06-01", as_of=date(2000, 6, 1))
    assert est["rate_source"] == "default"
    assert est["confidence"] == "low"


def test_proxy_basis_degrades_to_low():
    """A last-sale x LTV guess is a proxy, not a recorded principal."""
    est = estimate_current_balance(200000.0, "2022-06-01", basis="last_sale_ltv_proxy",
                                   as_of=date(2026, 8, 4))
    assert est["confidence"] == "low"


def test_bad_inputs_return_none():
    assert estimate_current_balance(None, "2020-01-01") is None
    assert estimate_current_balance(0, "2020-01-01") is None
    assert estimate_current_balance(100000.0, None) is None
    assert estimate_current_balance(100000.0, "not a date") is None


def test_fully_paid_note_estimates_zero():
    est = estimate_current_balance(100000.0, "1990-01-01", as_of=date(2026, 8, 4))
    assert est["estimated_balance"] == 0.0


def test_brand_new_note_estimates_the_full_principal():
    est = estimate_current_balance(250000.0, "2026-08-01", as_of=date(2026, 8, 4))
    assert est["estimated_balance"] == 250000.0


# --- equity wiring -----------------------------------------------------------
def _listing(**raw):
    from foreclosure_scraper.models import Listing
    li = Listing(source="t", source_url="https://x/y", state="NC", county="Burke")
    li.raw = dict(li.raw or {})
    li.raw.update(raw)
    return li


def test_equity_publishes_the_estimate_block_and_never_says_payoff():
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _listing(
        calc={"arv_expected": 300000.0},
        rod_docs=[{"doc_type": "DEED OF TRUST", "amount": 165000.0,
                   "recorded_date": "2019-04-12"}],
    )
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_source"] == "recorded_deed_of_trust"
    assert eq["payoff_is_estimate"] is True
    assert eq["payoff_label"] == "estimated balance"
    assert eq["payoff_method"] == "amortized_30yr_fixed"
    assert "ESTIMATE ONLY" in eq["payoff_disclaimer"]
    am = eq["amortization"]
    assert am["is_estimate"] is True and am["basis"] == "recorded_principal"
    assert am["original_principal"] == 165000.0
    assert am["rate_source"].startswith("pmms")


def test_equity_labels_the_last_sale_proxy_as_an_estimate_too():
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _listing(
        calc={"arv_expected": 300000.0},
        gis={"last_sale": {"amount": 200000.0, "date": "2018-05-01"}},
    )
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_source"].startswith("last_sale_amortized")
    assert eq["payoff_is_estimate"] is True
    assert eq["amortization"]["basis"] == "last_sale_ltv_proxy"
    assert eq["amortization"]["confidence"] == "low"


def test_equity_leaves_no_scratch_key_behind():
    """`_payoff` stashes the detail on raw; enrich_equity must consume it so the
    board never ships a private underscore key."""
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _listing(calc={"arv_expected": 300000.0},
                  rod_docs=[{"doc_type": "DT", "amount": 100000.0,
                             "recorded_date": "2020-01-01"}])
    enrich_equity([li])
    assert "_equity_amortization" not in li.raw


def test_equity_clears_the_scratch_key_when_no_payoff_resolves():
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _listing(calc={"arv_expected": 300000.0})   # no payoff input at all
    enrich_equity([li])
    assert "_equity_amortization" not in li.raw
    assert "equity" not in li.raw


def test_slashed_dt_code_is_recognised_as_a_deed_of_trust():
    """'D/T' is the code Logan and CCHS emit natively. It normalizes to 'D T',
    which was NOT in the accepted set, so a recorded principal harvested off an
    NC county index was silently ignored and the lead fell through to the far
    weaker opening-bid proxy. Live-caught on Burke 2026-08-04: 10 recorded
    principals written, 0 of them used."""
    from foreclosure_scraper.enrichment_equity import _is_deed_of_trust
    for t in ("D/T", "d/t", "DT", "MTG", "MORTGAGE", "DEED OF TRUST", "deed_of_trust"):
        assert _is_deed_of_trust(t) is True, t
    for t in ("TR/D", "M/SAT", "DEED", "PLAT", None, ""):
        assert _is_deed_of_trust(t) is False, t


def test_recorded_dt_with_a_slashed_code_beats_the_opening_bid_proxy():
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _listing(calc={"arv_expected": 250000.0},
                  rod_docs=[{"doc_type": "D/T", "amount": 109000.0,
                             "recorded_date": "2020-06-23"}])
    li.opening_bid = 180000.0
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_source"] == "recorded_deed_of_trust"
    assert eq["amortization"]["original_principal"] == 109000.0


def test_reported_debt_paths_are_still_flagged_as_estimates():
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _listing(calc={"arv_expected": 300000.0},
                  amount_owed={"value": 120000.0, "source": "judgment",
                               "is_actual_debt": True, "confidence": "high"})
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_is_estimate"] is True
    assert eq["payoff_method"] == "reported_debt:amount_owed:judgment"
    assert eq["amortization"] is None
