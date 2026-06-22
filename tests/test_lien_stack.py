"""Lien-stack join: state tax liens attach to matching owners (conservative)
and flow through to max-bid + equity as super-priority debt."""
from __future__ import annotations

from foreclosure_scraper.enrichment_lien_stack import enrich_lien_stack, _name_tokens
from foreclosure_scraper.enrichment_equity import enrich_equity
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.valuation import calc


def _lien_row(name, county="Gaston", amt=25000.0):
    return Listing(source="counties_sc.sc_state_tax_lien", source_url="u",
                   listing_type=ListingType.TAX_LIEN, state="SC", county=county,
                   defendant=name, judgment_amount=amt,
                   raw={"sc_state_tax_lien": {"kind": "individual", "balance": amt, "owner": name}})


def _subject(owner, county="Gaston", lt=ListingType.FORECLOSURE_SALE):
    return Listing(source="x", source_url="u", listing_type=lt, state="SC",
                   county=county, defendant=owner, raw={})


def test_name_tokens_order_insensitive_and_suffix_stripped():
    assert _name_tokens("SMITH, JOHN A JR") == _name_tokens("JOHN A SMITH")
    assert _name_tokens("John Smith") == frozenset({"JOHN", "SMITH"})


def test_exact_name_match_attaches_lien():
    lien = _lien_row("SMITH, JOHN", amt=30000)
    subj = _subject("JOHN SMITH")
    enrich_lien_stack([lien, subj])
    liens = subj.raw["liens"]
    assert len(liens) == 1
    assert liens[0]["amount"] == 30000 and liens[0]["super_priority"] is True


def test_no_match_different_county():
    lien = _lien_row("JOHN SMITH", county="Gaston")
    subj = _subject("JOHN SMITH", county="Pickens")
    enrich_lien_stack([lien, subj])
    assert "liens" not in subj.raw


def test_no_match_partial_name():
    lien = _lien_row("JOHN SMITH")
    subj = _subject("JOHN SMITHSON")
    enrich_lien_stack([lien, subj])
    assert "liens" not in subj.raw


def test_business_names_skipped():
    lien = _lien_row("ACME PROPERTIES LLC")
    subj = _subject("ACME PROPERTIES LLC")
    out = enrich_lien_stack([lien, subj])
    assert out["indexed"] == 0 and "liens" not in subj.raw


def test_lien_flows_into_equity_and_maxbid():
    lien = _lien_row("JOHN SMITH", amt=40000)
    subj = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="SC", county="Gaston", defendant="JOHN SMITH", living_sqft=1500,
                   opening_bid=50000,
                   raw={"comp_median_ppsf_recorded": 200.0,
                        "recorded_comps": {"median_ppsf": 200.0, "count": 10, "p25_ppsf": 180,
                                           "p75_ppsf": 220, "radius_mi": 1, "confidence": "HIGH"},
                        "amount_owed": {"value": 100000, "is_actual_debt": True},
                        "calc": {"arv_expected": 300000}})
    enrich_lien_stack([lien, subj])
    # max bid drops by the super-priority lien
    c_no = calc.compute(Listing(**{**subj.__dict__, "raw": {k: v for k, v in subj.raw.items() if k != "liens"}}))
    c_yes = calc.compute(subj)
    assert c_yes.max_bid_70 == c_no.max_bid_70 - 40000
    assert any("super-priority" in n for n in c_yes.notes)
    # equity subtracts it too
    enrich_equity([subj])
    assert subj.raw["equity"]["senior_liens"] == 40000
