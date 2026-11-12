"""Verified deed-signal additions + underwater soft-downgrade (2026-06-22).

Primary-source verified: DEED OF DISTRIBUTION (SC §62-3-907), DEED OF SEPARATION
(NC §39-13.4), COMMISSIONER'S DEED (partition/judicial sale). Underwater rule is
a SOFT risk downgrade gated to mortgage foreclosures with real ARV.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.enrichment_relationship_deeds import (
    _looks_probate, _looks_divorce, _looks_partition,
)
from foreclosure_scraper.distress_score import _signals_for
from foreclosure_scraper.valuation import grading, calc as _calc


def _l(doc, lt=ListingType.REO, **raw):
    r = {"doc_type": doc}
    r.update(raw)
    return Listing(source="x", source_url="u", listing_type=lt,
                   state="SC", county="Spartanburg", raw=r)


# --- deed-type matching ---
def test_deed_of_distribution_is_probate():
    assert _looks_probate(_l("Deed of Distribution")) == "DEED OF DISTRIBUTION"


def test_deed_of_separation_is_divorce_direct():
    # matches even with no consideration/grantor fields (bypasses the gate)
    assert _looks_divorce(_l("DEED OF SEPARATION")) == "deed_of_separation"
    assert _looks_divorce(_l("Memorandum of Separation")) == "deed_of_separation"


def test_commissioners_deed_is_partition_only():
    for doc in ("Commissioner's Deed", "COMMISSIONERS DEED"):
        li = _l(doc)
        assert _looks_partition(li)
        assert _looks_probate(li) is None
        assert _looks_divorce(li) is None


def test_bare_commissioner_not_partition():
    assert _looks_partition(_l("County Commissioner Meeting")) is None
    assert _looks_partition(_l("Warranty Deed")) is None


# --- distress scoring wiring (the latent-gap fix) ---
def _sig_names(li):
    return {s[0]: (s[1], s[2]) for s in _signals_for(li)}


def test_relationship_signal_scores():
    p = _l("x"); p.raw["relationship_signal"] = {"kind": "probate", "keyword": "DEED OF DISTRIBUTION"}
    assert _sig_names(p)["probate_deed"] == ("LIFE_EVENT", 20)

    d = _l("x"); d.raw["relationship_signal"] = {"kind": "divorce", "keyword": "couple_to_single_quitclaim"}
    assert _sig_names(d)["divorce"] == ("LIFE_EVENT", 15)

    dw = _l("x"); dw.raw["relationship_signal"] = {"kind": "divorce", "keyword": "zero_consideration_quitclaim"}
    assert _sig_names(dw)["divorce"] == ("LIFE_EVENT", 8)  # weaker (could be a gift)

    pt = _l("x"); pt.raw["relationship_signal"] = {"kind": "partition", "keyword": "COMMISSIONER'S DEED"}
    assert _sig_names(pt)["partition"] == ("SALES", 12)


# --- underwater soft-downgrade ---
def _c(arv, conf):
    c = _calc.Calc(); c.arv_expected = arv; c.arv_confidence = conf
    return c


def _fl(lt, judgment):
    return Listing(source="x", source_url="u", listing_type=lt, state="NC",
                   county="Gaston", judgment_amount=judgment)


def test_underwater_fires_on_mortgage_foreclosure():
    score, notes = grading._risk_score(_fl(ListingType.FORECLOSURE_SALE, 200000), _c(180000, "HIGH"))
    assert "underwater" in notes and score == 60  # 75 - 15


def test_underwater_excludes_tax_sale():
    score, notes = grading._risk_score(_fl(ListingType.TAX_SALE, 200000), _c(180000, "HIGH"))
    assert "underwater" not in notes


def test_underwater_needs_real_arv():
    _, notes = grading._risk_score(_fl(ListingType.FORECLOSURE_SALE, 200000), _c(180000, "LOW"))
    assert "underwater" not in notes  # bid-proxy ARV never triggers it


def test_underwater_skips_when_solvent():
    _, notes = grading._risk_score(_fl(ListingType.FORECLOSURE_SALE, 100000), _c(180000, "HIGH"))
    assert "underwater" not in notes


def test_risk_score_legacy_call_without_calc():
    score, _ = grading._risk_score(_fl(ListingType.FORECLOSURE_SALE, 200000))
    assert score == 75  # no Calc -> no underwater check, unchanged behavior
