"""Comp physical-adjustment grid + condition parity (29b)."""
from __future__ import annotations

from foreclosure_scraper import enrichment_comps as ec
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _subject(sqft=1500, baths=3, year=2000, lot=10000):
    return Listing(source="x", source_url="u", listing_type=ListingType.REO,
                   state="NC", county="Gaston", living_sqft=sqft, bathrooms=baths,
                   year_built=year, lot_size_sqft=lot, property_kind=PropertyKind.SINGLE_FAMILY)


def test_comp_condition_tier():
    assert ec._comp_condition_tier("Complete gut renovation needed") == "gut"
    assert ec._comp_condition_tier("Charming fixer-upper, sold as-is") == "major"
    assert ec._comp_condition_tier("Move-in ready, recently renovated") == "move_in_ready"
    assert ec._comp_condition_tier("") is None
    assert ec._comp_condition_tier("3 bed 2 bath ranch") is None


def test_gla_marginal_adjustment():
    # subject 1500, comp 1000 @ $200/sqft -> price 200k; GLA adj = 500*0.40*200 = 40k
    s = {"sold_price": 200000, "sqft": 1000}
    sub = _subject(sqft=1500, baths=None, year=None, lot=None)
    eff, adj = ec._adjust_comp(sub, s, base_ppsf=200.0)
    assert adj["gla"] == 40000
    assert eff == round(240000 / 1500, 2)   # 160.0


def test_bath_and_age_adjustments():
    s = {"sold_price": 200000, "sqft": 1500, "full_baths": 2, "year_built": 1980}
    sub = _subject(sqft=1500, baths=3, year=2000, lot=None)
    eff, adj = ec._adjust_comp(sub, s, base_ppsf=0)   # no GLA (base 0)
    assert adj["baths"] == 5000           # (3-2)*5000
    assert adj["age"] == 8000             # (2000-1980)*400
    assert eff == round((200000 + 13000) / 1500, 2)


def test_gross_adjustment_capped_at_25pct():
    # huge GLA delta would blow past 25% of price -> capped
    s = {"sold_price": 200000, "sqft": 500}
    sub = _subject(sqft=4000, baths=None, year=None, lot=None)
    eff, adj = ec._adjust_comp(sub, s, base_ppsf=300.0)
    assert adj["capped"] is True
    assert adj["net"] == 50000            # 25% of 200k
    assert eff == round(250000 / 4000, 2)


def test_adjust_comp_bad_inputs():
    assert ec._adjust_comp(_subject(), {"sold_price": 0, "sqft": 1000}, 200)[0] is None
    assert ec._adjust_comp(_subject(sqft=None), {"sold_price": 200000, "sqft": 1000}, 200)[0] is None


def test_pick_3_comps_attaches_adjusted_ppsf_and_drops_gut():
    sub = _subject()
    pool = []
    # 3 retail comps (move-in) + 2 gut comps, same zip/kind/sqft band
    for i, (price, txt) in enumerate([
            (300000, "move-in ready"), (310000, "updated"), (305000, "renovated"),
            (150000, "complete gut renovation"), (140000, "tear-down shell only")]):
        pool.append({
            "sold_price": price, "sqft": 1500, "beds": 3, "full_baths": 3,
            "year_built": 2000, "lot_sqft": 10000, "zip_code": "28052",
            "city": "Gastonia", "state": "NC", "style": "SINGLE_FAMILY",
            "property_type": "SINGLE_FAMILY", "text": txt,
            "last_sold_date": f"2026-0{i+1}-01", "property_url": f"http://c/{i}",
        })
    sub.zip_code = "28052"
    out = ec._pick_3_comps(sub, pool)
    assert out, "expected comps"
    # gut/tear-down comps dropped by condition parity
    assert all("gut" not in (c.get("address") or "") for c in out)
    assert all(c["sold_price"] >= 300000 for c in out)
    # adjusted ppsf attached
    assert any(c.get("adjusted_ppsf") for c in out)
