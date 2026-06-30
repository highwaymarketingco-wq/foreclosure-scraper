"""Comp-accuracy deal math: rehab contingency, wholesale MAO, and comp-quality
confidence gating for scraped comps."""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc


def _recorded_arv_listing(**kw):
    raw = {"comp_median_ppsf_recorded": 200.0,
           "recorded_comps": {"median_ppsf": 200.0, "count": 10, "p25_ppsf": 180,
                              "p75_ppsf": 220, "radius_mi": 1, "confidence": "HIGH"},
           "condition_tier": "cosmetic"}
    raw.update(kw.pop("raw", {}))
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", living_sqft=1500,
                   property_kind=PropertyKind.SINGLE_FAMILY, raw=raw, **kw)


def test_rehab_contingency_applied_to_max_bid():
    c = calc.compute(_recorded_arv_listing(opening_bid=50000))
    assert c.arv_expected == 300000
    assert c.rehab_expected is not None
    assert c.rehab_with_contingency == round(c.rehab_expected * 1.125, -2)
    # 70% rule, post-calibration (backtest n=266): the 30% haircut already embeds selling cost,
    # so max_bid = 0.75*ARV - rehab (no separate fee — the old formula double-charged ~7% of ARV).
    assert c.max_bid_70 == round(0.75 * 300000 - c.rehab_with_contingency, -2)


def test_wholesale_mao_and_spread():
    c = calc.compute(_recorded_arv_listing(opening_bid=40000))
    assert c.wholesale_mao == round(c.max_bid_70 - calc.ASSIGNMENT_FEE, -2)
    assert c.wholesale_spread == round(c.max_bid_70 - 40000, -2)


def _scraped(comps, ppsf):
    return Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                   county="Gaston", living_sqft=1500,
                   raw={"comps": comps, "comp_median_ppsf": ppsf})


def test_scraped_comps_high_when_enough_anchored_tight():
    comps = [{"price_per_sqft": p, "geo_anchored": True} for p in (190, 200, 210)]
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "HIGH"


def test_scraped_comps_medium_when_too_few():
    comps = [{"price_per_sqft": 200, "geo_anchored": True}]
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "MEDIUM"
    assert any("only 1 comp" in n for n in c.notes)


def test_scraped_comps_medium_when_not_geo_anchored():
    comps = [{"price_per_sqft": p, "geo_anchored": False} for p in (190, 200, 210)]
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "MEDIUM"
    assert any("county-wide" in n for n in c.notes)


def test_scraped_comps_medium_when_dispersed():
    comps = [{"price_per_sqft": p, "geo_anchored": True} for p in (120, 200, 260)]  # 2.17x spread
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "MEDIUM"
    assert any("disagree" in n for n in c.notes)


def test_recorded_comps_unaffected_by_scraped_gate():
    # Tier-0 recorded comps return before Tier-1 scraped gating.
    c = calc.compute(_recorded_arv_listing())
    assert c.arv_confidence == "HIGH"
