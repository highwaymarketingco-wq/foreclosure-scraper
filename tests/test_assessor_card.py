"""Grade-gated on-demand assessor-card enricher — gate, fill-only-missing, parsing."""
from __future__ import annotations

import os
from types import SimpleNamespace

from foreclosure_scraper.assessor_cards.base import (
    CardResult, CardSale, epoch_ms_to_iso, money,
)
from foreclosure_scraper.assessor_cards import anderson_sc
from foreclosure_scraper import enrichment_assessor_card as eac


# ---- base helpers ----

def test_money_and_epoch():
    assert money("$1,840,000.00") == 1840000.0
    assert money(1840000) == 1840000.0
    assert money(0) is None and money(None) is None and money("n/a") is None
    assert epoch_ms_to_iso(1761609600000) == "2025-10-28"
    assert epoch_ms_to_iso(0) is None and epoch_ms_to_iso(None) is None


def test_best_sale_price_skips_nominal_and_family():
    res = CardResult(source_url="x", sales=[
        CardSale(sale_date="2025-10-28", price=5, reason="Improved"),        # nominal
        CardSale(sale_date="2025-04-09", price=1840000, reason="Improved"),  # arms-length
        CardSale(sale_date="2018-12-13", price=27500, reason="Not Valid"),   # flagged invalid
    ])
    # newest valid arms-length wins; the $5 nominal + "Not Valid" rows are skipped
    assert res.best_sale_price() == 1840000.0


def test_anderson_parse_sales_newest_first():
    feats = [
        {"attributes": {"SALEDATE": 1710028800000, "SAPRIC": 5, "SADEBK": "17881 ", "SADEPG": 147, "SATYPE": "Improved"}},
        {"attributes": {"SALEDATE": 1761609600000, "SAPRIC": 1840000, "SADEBK": "18360 ", "SADEPG": 242, "SATYPE": "Improved"}},
    ]
    sales = anderson_sc._parse_sales(feats)
    assert sales[0].price == 1840000.0 and sales[0].book == "18360" and sales[0].page == "242"
    assert sales[0].sale_date == "2025-10-28"   # newest first


# ---- gate + fill-only-missing ----

def _lead(grade, **kw):
    li = SimpleNamespace(state="SC", county="Anderson", parcel_id="671103001",
                         living_sqft=None, living_sqft_estimated=False, year_built=None,
                         bedrooms=None, bathrooms=None, market_value=None, source_url="u",
                         raw={"grade": {"overall": grade}})
    for k, v in kw.items():
        setattr(li, k, v)
    return li


def test_grade_gate():
    assert eac._is_bplus(_lead("A")) and eac._is_bplus(_lead("B"))
    assert not eac._is_bplus(_lead("C")) and not eac._is_bplus(_lead("F"))


def test_apply_fills_only_missing_and_clears_estimate():
    li = _lead("B", living_sqft=1200.0, living_sqft_estimated=True, market_value=None)
    res = CardResult(source_url="card", living_sqft=2371.0, living_sqft_is_heated=True,
                     year_built=1956, market_value=384600.0,
                     sales=[CardSale(sale_date="2016-11-08", price=250000, reason="Improved")])
    stats = {"filled_sqft": 0, "filled_price": 0}
    eac._apply(li, res, stats)
    # estimate replaced by real card sqft + flag cleared
    assert li.living_sqft == 2371.0 and li.living_sqft_estimated is False
    assert li.year_built == 1956 and li.market_value == 384600.0
    assert li.raw["assessor_card"]["sale_price"] == 250000
    assert stats == {"filled_sqft": 1, "filled_price": 1}


def test_apply_does_not_overwrite_real_sqft():
    li = _lead("B", living_sqft=1800.0, living_sqft_estimated=False)
    res = CardResult(source_url="card", living_sqft=2371.0)
    eac._apply(li, res, {"filled_sqft": 0, "filled_price": 0})
    assert li.living_sqft == 1800.0   # real value preserved, not clobbered


def test_enricher_off_by_default():
    os.environ.pop("ASSESSOR_CARD_ON", None)
    assert eac.enrich_assessor_card([_lead("B")]) == {}


# ---- UNLOCK 3: widened gate (eligibility / rank / cap) ----

def _qp_lead(grade=None, *, kind="single_family", living_sqft=None,
             living_sqft_estimated=False, parcel_id="520-29-06-013",
             latitude=34.7, longitude=-83.0, distress=0, county="Oconee"):
    from foreclosure_scraper.models import PropertyKind
    raw = {"grade": {"overall": grade}, "distress_stack": {"score": distress}}
    return SimpleNamespace(
        state="SC", county=county, parcel_id=parcel_id, property_kind=PropertyKind(kind),
        living_sqft=living_sqft, living_sqft_estimated=living_sqft_estimated,
        latitude=latitude, longitude=longitude, raw=raw)


_ADAPTERS = {("SC", "Oconee"): None, ("SC", "Pickens"): None,
             ("SC", "Spartanburg"): None, ("SC", "Union"): None}


def test_eligible_grades_default_admits_unrated():
    os.environ.pop("ASSESSOR_CARD_GRADES", None)
    g = eac._eligible_grades()
    assert {"A", "B", "C", ""} <= g
    # blank token => None-grade admitted
    assert eac._grade_ok(_qp_lead(grade=None), g)
    assert eac._grade_ok(_qp_lead(grade="C"), g)


def test_grades_env_restores_strict_ab():
    os.environ["ASSESSOR_CARD_GRADES"] = "A,B"
    g = eac._eligible_grades()
    assert eac._grade_ok(_qp_lead(grade="A"), g)
    assert not eac._grade_ok(_qp_lead(grade="C"), g)
    assert not eac._grade_ok(_qp_lead(grade=None), g)
    os.environ.pop("ASSESSOR_CARD_GRADES", None)


def test_card_eligible_includes_c_and_unrated_built():
    g = eac._eligible_grades()  # default
    assert eac._is_card_eligible(_qp_lead(grade="C"), g, _ADAPTERS, False)
    assert eac._is_card_eligible(_qp_lead(grade=None), g, _ADAPTERS, False)


def test_card_eligible_excludes_vacant_land_and_filled_sqft():
    g = eac._eligible_grades()
    # vacant land -> no heated sqft on a card -> excluded
    assert not eac._is_card_eligible(_qp_lead(grade=None, kind="land"), g, _ADAPTERS, False)
    # already has a real (non-estimated) sqft -> nothing to fill
    assert not eac._is_card_eligible(
        _qp_lead(grade="C", living_sqft=1800.0, living_sqft_estimated=False),
        g, _ADAPTERS, False)
    # estimated sqft still needs a real card sqft -> eligible
    assert eac._is_card_eligible(
        _qp_lead(grade="C", living_sqft=1800.0, living_sqft_estimated=True),
        g, _ADAPTERS, False)


def test_card_eligible_requires_key_and_known_county():
    g = eac._eligible_grades()
    # no parcel_id and no lat/lng -> no lookup key -> excluded
    assert not eac._is_card_eligible(
        _qp_lead(grade="C", parcel_id=None, latitude=None, longitude=None),
        g, _ADAPTERS, False)
    # SC lat/lng with no parcel_id is still a key (resolver path)
    assert eac._is_card_eligible(
        _qp_lead(grade="C", parcel_id=None), g, _ADAPTERS, False)
    # county with no adapter in the table -> excluded
    assert not eac._is_card_eligible(
        _qp_lead(grade="C", county="Greenville"), g, _ADAPTERS, False)


def test_skip_render_excludes_render_counties():
    g = eac._eligible_grades()
    li = _qp_lead(grade="C", county="Oconee")  # a render-class county
    assert eac._is_card_eligible(li, g, _ADAPTERS, False)
    assert not eac._is_card_eligible(li, g, _ADAPTERS, True)


def test_rank_orders_grade_then_distress():
    a = _qp_lead(grade="A", distress=10)
    c_hi = _qp_lead(grade="C", distress=90)
    none_lo = _qp_lead(grade=None, distress=5)
    ranked = sorted([none_lo, c_hi, a], key=eac._rank_key, reverse=True)
    assert ranked[0] is a            # grade rank wins first
    assert ranked[1] is c_hi         # then distress score
    assert ranked[2] is none_lo
