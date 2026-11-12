"""Pass-2 regression tests: bugs the adversarial re-audit found in Pass-1 code."""
from __future__ import annotations

from datetime import date

from foreclosure_scraper import enrichment_comps as ec
from foreclosure_scraper import enrichment_equity as eq
from foreclosure_scraper.models import Listing, ListingType


# --- equity: last-sale arms-length gate (the $1-transfer -> fake-equity bug) ---
def test_nominal_transfer_does_not_fabricate_equity():
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                 county="Gaston", market_value=300000,
                 raw={"gis": {"last_sale": {"amount": 100, "date": "2015-01-01"}}})
    eq.enrich_equity([li])
    # $100 intra-family transfer is below the floor -> no payoff -> no fake equity
    assert "equity" not in li.raw


def test_real_sale_still_produces_equity():
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                 county="Gaston", market_value=300000,
                 raw={"gis": {"last_sale": {"amount": 150000, "date": "2015-01-01"}}})
    eq.enrich_equity([li])
    assert li.raw["equity"]["payoff_source"] == "last_sale_amortized"


# --- equity: _recorded_dt compares PARSED dates, not raw strings ---
def test_recorded_dt_picks_newer_by_parsed_date():
    raw = {"rod_docs": [
        {"doc_type": "DEED OF TRUST", "amount": 400000, "recorded_date": "2010-01-01"},
        {"doc_type": "DEED OF TRUST", "amount": 100000, "recorded_date": "12/01/2022"},
    ]}
    amt, dt = eq._recorded_dt(raw)
    assert amt == 100000 and dt == "12/01/2022"   # newer note, not the older/larger one


# --- equity._senior_liens mirrors calc (fpos gate + super-priority) ---
def test_senior_liens_gated_on_foreclosure_position():
    assert eq._senior_liens({"lien_priority": {"total_senior_amount": 50000, "foreclosure_position": 1}}) == 0.0
    assert eq._senior_liens({"lien_priority": {"total_senior_amount": 50000, "foreclosure_position": 2}}) == 50000.0


def test_senior_liens_adds_super_priority_on_top():
    raw = {"lien_priority": {"total_senior_amount": 50000, "foreclosure_position": 2},
           "liens": [{"amount": 20000, "super_priority": True}]}
    assert eq._senior_liens(raw) == 70000.0


# --- comps: market-velocity fetch-failure must NOT look like a hot market ---
def test_active_fetch_failure_falls_back_to_neutral_holding():
    assert ec._months_of_inventory(None, 60) is None     # fetch failed
    assert ec._months_of_inventory(0, 60) is None        # 0 active ~ failed pull
    assert ec._holding_months_from_moi(None) == 6        # neutral, not optimistic 4


# --- comps: 25% cap flags on GROSS adjustment, not net ---
def test_gross_cap_flags_offsetting_adjustments():
    s = {"sold_price": 200000, "sqft": 1000, "full_baths": 10, "year_built": 2100}
    sub = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                  county="Gaston", living_sqft=2000, bathrooms=1, year_built=1900)
    _, adj = ec._adjust_comp(sub, s, base_ppsf=200.0)
    # GLA up, baths way down, age down — net may be modest but GROSS is huge -> flagged
    assert adj["gross"] > 0.25 * 200000
    assert adj["capped"] is True
