"""Stored bankruptcy matches are re-judged every run, offline (2026-10-06).

The 2026-10-02 matcher fix only changed how NEW matches are made; every raw['bankruptcy'] on the
board was still the old bag-of-tokens match and kept showing a stranger's case (and the stay
derived from it) on the property. enrichment_bankruptcy.rejudge_existing_matches re-applies
the current rule to the stored case name. All names here are made up.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper import enrichment_bankruptcy as eb
from foreclosure_scraper.enrichment_bankruptcy_stay import enrich_bankruptcy_stay
from foreclosure_scraper.models import Listing, ListingType


def _bk(case_name, court="ncwb", docket="26-10001", **kw):
    return {"court": court, "case_name": case_name, "docket_number": docket,
            "date_filed": "2026-09-01", "chapter": "13", "absolute_url": "/docket/1/x/",
            "match_strategy": "strict_subset", **kw}


def _stay(docket="26-10001", status="stayed"):
    return {"status": status, "chapter": "13", "docket": docket, "court": "ncwb",
            "case": "whatever", "date_filed": "2026-09-01"}


def _li(defendant, bk, *, state="NC", stay=None, lt=ListingType.FORECLOSURE_SALE):
    raw = {"bankruptcy": bk}
    if stay is not None:
        raw["bankruptcy_stay"] = stay
    return Listing(source="t", source_url="http://x", state=state, county="Buncombe",
                   listing_type=lt, defendant=defendant, raw=raw)


@pytest.mark.parametrize("defendant,case_name,state,court,reason", [
    # position-blind: the defendant's first name is the debtor's MIDDLE name
    ("PEMBERTON, ALDOUS", "Corwin Aldous Pemberton", "NC", "ncwb", "no_positional_match"),
    # joint-filer phantom: first name of debtor 1 + last name of debtor 2
    ("VANTERPOOL, ODELL", "Odell Ray Brisco and Tamsin Lee Vanterpool", "NC", "nceb",
     "no_positional_match"),
    # same first + last, every such debtor's middle initial contradicts the owner's
    ("QUILLFEATHER, MARA T", "Mara Jean Quillfeather", "NC", "ncwb", "middle_conflict"),
    # a NC court for an SC property
    ("QUILLFEATHER, MARA", "Mara Jean Quillfeather", "SC", "ncwb", "court_state_differs"),
    # an ALL-CAPS FIRST LAST name whose FIRST LAST reading is a proven conflict
    ("MARA T QUILLFEATHER", "Mara Jean Quillfeather", "NC", "ncwb", "middle_conflict"),
])
def test_wrong_person_matches_are_rejected(defendant, case_name, state, court, reason):
    assert eb.rejudge_match(defendant, state, _bk(case_name, court=court)) == (False, reason)


@pytest.mark.parametrize("defendant,case_name,state,court,reason", [
    ("QUILLFEATHER, MARA", "Mara Jean Quillfeather", "NC", "ncwb", "positional_match_unverified"),
    ("QUILLFEATHER, MARA J", "Mara Jean Quillfeather", "NC", "ncwb", "positional_match_agrees"),
    ("QUILLFEATHER MARA J", "Odell Brisco and Mara Jean Quillfeather", "NC", "nceb",
     "positional_match_agrees"),
    ("Mara Quillfeather", "Mara Jean Quillfeather", "SC", "scb", "positional_match_unverified"),
    # cannot judge: kept as is
    ("QUILLFEATHER, MARA", "", "NC", "ncwb", "unjudgeable_no_case_name"),
    (None, "Mara Jean Quillfeather", "NC", "ncwb", "unjudgeable_defendant"),
    ("QUILLFEATHER", "Mara Jean Quillfeather", "NC", "ncwb", "unjudgeable_defendant"),
    ("MARA QUILLFEATHER", "Mara Quillfeather", "NC", "ncwb", "order_ambiguous"),
    # a court the rule has no state for is not a state mismatch
    ("QUILLFEATHER, MARA", "Mara Jean Quillfeather", "SC", "xxb", "positional_match_unverified"),
])
def test_matches_the_rule_accepts_or_cannot_judge_are_kept(defendant, case_name, state, court,
                                                           reason):
    assert eb.rejudge_match(defendant, state, _bk(case_name, court=court)) == (True, reason)


def test_rejudge_clears_the_match_and_the_stay_derived_from_it():
    wrong = _li("PEMBERTON, ALDOUS", _bk("Corwin Aldous Pemberton"), stay=_stay())
    lapsed = _li("PEMBERTON, ALDOUS", _bk("Corwin Aldous Pemberton"),
                 stay={"status": "lapsed", "chapter": "13", "date_filed": "2016-01-01"})
    other_case = _li("PEMBERTON, ALDOUS", _bk("Corwin Aldous Pemberton"),
                     stay=_stay(docket="25-99999"))
    right = _li("QUILLFEATHER, MARA", _bk("Mara Jean Quillfeather"), stay=_stay())
    stats = eb.rejudge_existing_matches([wrong, lapsed, other_case, right])
    assert "bankruptcy" not in wrong.raw and "bankruptcy_stay" not in wrong.raw
    assert "bankruptcy" not in lapsed.raw and "bankruptcy_stay" not in lapsed.raw
    assert "bankruptcy" not in other_case.raw and other_case.raw["bankruptcy_stay"]["docket"] == "25-99999"
    assert right.raw["bankruptcy"]["case_name"] == "Mara Jean Quillfeather"
    assert right.raw["bankruptcy_stay"]["status"] == "stayed"
    assert stats == {"checked": 4, "kept": 1, "cleared": 3, "cleared_stays": 2,
                     "no_positional_match": 3, "positional_match_unverified": 1}
    again = eb.rejudge_existing_matches([wrong, lapsed, other_case, right])
    assert again["checked"] == 1 and again["cleared"] == 0          # idempotent


def test_the_stay_enricher_does_not_bring_a_cleared_stay_back():
    li = _li("PEMBERTON, ALDOUS", _bk("Corwin Aldous Pemberton"), stay=_stay())
    eb.rejudge_existing_matches([li])
    enrich_bankruptcy_stay([li])
    assert "bankruptcy" not in li.raw and "bankruptcy_stay" not in li.raw


def test_rows_without_a_match_are_untouched():
    li = Listing(source="t", source_url="http://x", state="NC", county="Buncombe",
                 defendant="PEMBERTON, ALDOUS", raw={"bankruptcy_stay": _stay(), "x": 1})
    assert eb.rejudge_existing_matches([li])["checked"] == 0
    assert li.raw == {"bankruptcy_stay": _stay(), "x": 1}


def test_enrich_rejudges_even_without_a_token_and_never_touches_the_network(monkeypatch):
    monkeypatch.setattr(eb, "_load_token", lambda: None)

    def boom(*a, **k):
        raise AssertionError("no network without a token")

    monkeypatch.setattr(eb, "client", boom)
    wrong = _li("PEMBERTON, ALDOUS", _bk("Corwin Aldous Pemberton"), stay=_stay())
    right = _li("QUILLFEATHER, MARA", _bk("Mara Jean Quillfeather"))
    asyncio.run(eb.enrich_with_bankruptcy([wrong, right]))
    assert "bankruptcy" not in wrong.raw and "bankruptcy_stay" not in wrong.raw
    assert "bankruptcy" in right.raw
