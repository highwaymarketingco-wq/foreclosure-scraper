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
