"""Owner-equity engine + amortization + senior-lien-aware max bid."""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_equity import enrich_equity
from foreclosure_scraper.valuation import amortize, calc
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.distress_score import _equity_band


# ---- amortization -------------------------------------------------------
def test_amortized_balance_pays_down_over_time():
    # 200k @ ~4% (2018) 30yr, 6 years in -> below original, above zero
    bal = amortize.amortized_balance(200000, date(2018, 1, 1), as_of=date(2024, 1, 1))
    assert bal is not None and 150000 < bal < 185000


def test_amortized_fresh_loan_full_balance():
    assert amortize.amortized_balance(200000, date(2024, 1, 1), as_of=date(2024, 1, 1)) == 200000.0


def test_amortized_matured_loan_zero():
    assert amortize.amortized_balance(200000, date(1985, 1, 1), as_of=date(2024, 1, 1)) == 0.0


def test_amortized_bad_inputs_none():
    assert amortize.amortized_balance(0, date(2020, 1, 1)) is None
    assert amortize.amortized_balance(200000, None) is None


def test_amortize_parses_string_dates():
    assert amortize._as_date("2018-01-01") == date(2018, 1, 1)
    assert amortize._as_date("01/15/2019") == date(2019, 1, 15)
    assert amortize._as_date("20200601") == date(2020, 6, 1)


# ---- equity engine ------------------------------------------------------
def test_equity_from_actual_debt():
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Gaston",
                 raw={"calc": {"arv_expected": 300000},
                      "amount_owed": {"value": 120000, "source": "judgment",
                                      "is_actual_debt": True, "confidence": "high"}})
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["value"] == 180000 and eq["pct"] == 0.6
    assert eq["payoff_source"].startswith("amount_owed") and eq["confidence"] == "high"
    assert eq["is_underwater"] is False


def test_equity_underwater_with_senior_liens():
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Gaston",
                 raw={"calc": {"arv_expected": 200000},
                      "amount_owed": {"value": 190000, "is_actual_debt": True},
                      "lien_priority": {"total_senior_amount": 40000}})
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["value"] == -30000 and eq["is_underwater"] is True
    assert eq["senior_liens"] == 40000


def test_equity_from_last_sale_amortized():
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="NC", county="Gaston", market_value=250000,
                 raw={"gis": {"last_sale": {"amount": 150000, "date": "2015-06-01"}}})
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_source"] == "last_sale_amortized" and eq["confidence"] == "low"
    assert eq["value"] > 0   # paid-down loan on a 250k-value home -> positive equity


def test_last_sale_rejects_corrupt_billion_dollar_amount():
    """Regression: a corrupt GIS last-sale amount (concatenated book+page / cents /
    parcel id leak) must NOT amortize to a billion-dollar payoff. The path-3 upper
    bound rejects sale_amt > 3x ARV and any resulting payoff > 2x ARV."""
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="SC", county="Spartanburg", market_value=234900,
                 raw={"calc": {"arv_expected": 234900},
                      "gis": {"last_sale": {"amount": 1038143000, "date": "2015-06-01"}}})
    enrich_equity([li])
    eq = li.raw.get("equity") or {}
    # corrupt amount rejected -> path 3 yields no payoff -> no equity row (not a
    # $934M payoff). A legit sale on the same home still works (other test).
    assert not eq, f"corrupt billion-dollar last-sale should be rejected, got {eq}"


def test_last_sale_legit_amount_still_works():
    """The upper-bound gate must not reject a normal in-band sale."""
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="SC", county="Spartanburg", market_value=234900,
                 raw={"calc": {"arv_expected": 234900},
                      "gis": {"last_sale": {"amount": 180000, "date": "2015-06-01"}}})
    enrich_equity([li])
    eq = li.raw.get("equity") or {}
    assert eq.get("payoff_source") == "last_sale_amortized"
    assert eq["payoff_estimate"] <= 2 * eq["arv_used"]


def test_recorded_dot_is_top_payoff_tier_high_confidence():
    """A populated raw['rod_docs'] Deed-of-Trust (original principal + recorded
    date) must be consumed as the #1 HIGH-confidence payoff source, ahead of any
    judgment/opening-bid/last-sale fallback. Locks the equity reader contract so
    the ROD enrichment unlock pays off the moment a vendor exposes the amount."""
    li = Listing(source="x", source_url="u", listing_type=ListingType.LIS_PENDENS,
                 state="SC", county="Pickens",
                 raw={"calc": {"arv_expected": 300000},
                      # also carries a (weaker) judgment that MUST be overridden
                      "amount_owed": {"value": 250000, "source": "judgment",
                                      "is_actual_debt": True, "confidence": "high"},
                      "rod_docs": [{"doc_type": "deed_of_trust", "amount": 200000,
                                    "recorded_date": "2021-06-01"}]})
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["payoff_source"] == "recorded_deed_of_trust" and eq["confidence"] == "high"
    # 200k note recorded 2021 has paid down -> payoff < 200k -> equity > 100k
    assert eq["payoff_estimate"] < 200000 and eq["value"] > 100000


def test_recorded_dot_label_variants_all_match():
    """The DoT matcher must accept every label form feeds/contracts emit —
    underscore ('deed_of_trust'), spaced ('DEED OF TRUST'), short codes (DT/MTG/
    MORTGAGE). Regression: the underscore form used to fall through to 0 equity."""
    from foreclosure_scraper.enrichment_equity import _is_deed_of_trust
    for good in ("deed_of_trust", "DEED OF TRUST", "Deed of Trust", "deed-of-trust",
                 "DT", "MTG", "MORT", "MORTGAGE"):
        assert _is_deed_of_trust(good), good
    for bad in ("DEED", "SATISFACTION", "LIEN", "", None):
        assert not _is_deed_of_trust(bad), bad


def test_equity_band_uses_real_equity_not_roi():
    # The calc block carries an `arv_expected`, which it must: `roi_pct` is an
    # ARV-derived money field, so `roi_pct` WITHOUT an ARV is the state
    # board_qa's `derived_without_arv` tripwire declares must never exist, and
    # `_equity_band` now refuses to rank on it (a published equity pct with no
    # ARV behind it was computed off the market_value fallback — see the
    # `valuation_ran_without_arv` block in enrichment_equity). The assertion
    # this test actually makes — equity pct beats roi_pct — is unchanged.
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                 county="Gaston",
                 raw={"equity": {"pct": 0.55},
                      "calc": {"arv_expected": 250000.0, "roi_pct": 5}})
    assert _equity_band(li) == "high"      # 55% equity -> high, despite low ROI
    li.raw["equity"]["pct"] = -0.1
    assert _equity_band(li) == "low"       # underwater -> low


# ---- senior-lien-aware max bid + HIGH confidence ------------------------
def test_senior_liens_cut_max_bid_on_junior_foreclosure():
    base = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", living_sqft=1500, opening_bid=50000,
                   raw={"comp_median_ppsf_recorded": 200.0,
                        "recorded_comps": {"median_ppsf": 200.0, "count": 10,
                                           "p25_ppsf": 180, "p75_ppsf": 220,
                                           "radius_mi": 1, "confidence": "HIGH"}})
    clean = calc.compute(base)
    junior = Listing(**{**base.__dict__})
    junior.raw = dict(base.raw)
    junior.raw["lien_priority"] = {"total_senior_amount": 80000, "foreclosure_position": 2}
    jr = calc.compute(junior)
    assert jr.max_bid_70 == clean.max_bid_70 - 80000
    assert any("senior lien" in n.lower() for n in jr.notes)


def test_high_arv_confidence_now_scores():
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                 county="Gaston", living_sqft=1500, year_built=1990,
                 raw={"comp_median_ppsf_recorded": 200.0,
                      "recorded_comps": {"median_ppsf": 200.0, "count": 10, "p25_ppsf": 180,
                                         "p75_ppsf": 220, "radius_mi": 1, "confidence": "HIGH"}})
    c = calc.compute(li)
    assert c.arv_confidence == "HIGH"
    assert c.confidence == "HIGH"   # HIGH arv (+3) + sqft (+1) + year (+1) = 5
