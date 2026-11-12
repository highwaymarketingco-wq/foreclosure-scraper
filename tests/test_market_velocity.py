"""Market velocity: months-of-inventory -> per-listing holding period in calc."""
from __future__ import annotations

from foreclosure_scraper import enrichment_comps as ec
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.valuation import calc


def test_months_of_inventory():
    # 60 active, 60 sold over 6mo (10/mo) -> 6.0 MOI
    assert ec._months_of_inventory(60, 60) == 6.0
    # 10 active, 120 sold over 6mo (20/mo) -> 0.5 MOI (hot)
    assert ec._months_of_inventory(10, 120) == 0.5
    # no sales -> unknown
    assert ec._months_of_inventory(50, 0) is None


def test_holding_months_from_moi():
    assert ec._holding_months_from_moi(None) == 6
    assert ec._holding_months_from_moi(1.0) == 4    # seller's market, fast
    assert ec._holding_months_from_moi(4.0) == 6    # balanced
    assert ec._holding_months_from_moi(9.0) == 9    # buyer's market, slow


def _li(holding_est=None):
    raw = {"comp_median_ppsf_recorded": 200.0,
           "recorded_comps": {"median_ppsf": 200.0, "count": 10, "p25_ppsf": 180,
                              "p75_ppsf": 220, "radius_mi": 1, "confidence": "HIGH"}}
    if holding_est is not None:
        raw["market_velocity"] = {"holding_months_est": holding_est, "moi": 9.0}
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", living_sqft=1500, opening_bid=80000, raw=raw)


def test_calc_uses_market_velocity_holding():
    slow = calc.compute(_li(holding_est=9))   # buyer's market
    base = calc.compute(_li(holding_est=None))  # default 6
    # slower market -> more holding cost -> higher total investment, lower profit
    assert slow.total_investment > base.total_investment
    assert slow.estimated_profit < base.estimated_profit
