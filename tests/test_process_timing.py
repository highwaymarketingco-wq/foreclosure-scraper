"""Foreclosure-process + SC redemption-clock labels + their risk effect."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_process_timing import enrich_process_timing
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.valuation import calc as _calc
from foreclosure_scraper.valuation.grading import _risk_score


def _li(state, lt, **kw):
    return Listing(source="x", source_url="u", listing_type=lt, state=state,
                   county=kw.pop("county", "Gaston"), **kw)


def test_nc_foreclosure_is_power_of_sale():
    li = _li("NC", ListingType.FORECLOSURE_SALE)
    enrich_process_timing([li])
    assert li.foreclosure_process == "power_of_sale"
    assert li.redemption_deadline is None


def test_sc_foreclosure_is_judicial():
    li = _li("SC", ListingType.FORECLOSURE_SALE)
    enrich_process_timing([li])
    assert li.foreclosure_process == "judicial"


def test_sc_tax_sale_sets_redemption_clock():
    li = _li("SC", ListingType.TAX_SALE, sale_date=datetime(2026, 1, 15))
    out = enrich_process_timing([li])
    assert li.foreclosure_process == "tax"
    assert li.redemption_deadline == datetime(2027, 1, 15)
    assert out["sc_redemption_clocks"] == 1


def test_nc_tax_sale_no_redemption_clock():
    li = _li("NC", ListingType.TAX_SALE, sale_date=datetime(2026, 1, 15))
    enrich_process_timing([li])
    assert li.foreclosure_process == "tax"
    assert li.redemption_deadline is None   # NC tax foreclosure conveys at sale


def test_judicial_lowers_risk_score_vs_power_of_sale():
    nc = _li("NC", ListingType.FORECLOSURE_SALE)
    sc = _li("SC", ListingType.FORECLOSURE_SALE)
    enrich_process_timing([nc, sc])
    nc_score, _ = _risk_score(nc, _calc.compute(nc))
    sc_score, sc_notes = _risk_score(sc, _calc.compute(sc))
    assert nc_score > sc_score
    assert "judicial" in sc_notes.lower()


def test_redemption_adds_risk_note():
    li = _li("SC", ListingType.TAX_SALE, sale_date=datetime(2026, 1, 15))
    enrich_process_timing([li])
    _, notes = _risk_score(li, _calc.compute(li))
    assert "redemption" in notes.lower()
