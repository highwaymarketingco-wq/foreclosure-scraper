"""Forced-sale deeds must survive the ROD classifiers (finding F1).

TR/D, COM/D and SHF/D are what CCHS serves. They matched none of rod.classify's
keyword lists, so they never reached raw['rod'].instruments, and the deed-chain
filter and _DISTRESS_TYPES missed them too. The rows below are real-layout CCHS
party rows with placeholder names, read through the production _parse_rows.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from foreclosure_scraper.enrichment_deed_chain import _is_distress_sale
from foreclosure_scraper.rod import cchs
from foreclosure_scraper.rod import inst_class as ic
from foreclosure_scraper.rod.classify import classify_rod_docs
from foreclosure_scraper.rod.models import RodDoc, normalize_doc_type

ROWS_XML = (Path(__file__).parent / "fixtures" / "cchs_loss_deed_rows_synthetic.xml").read_text()


def _docs():
    return cchs._parse_rows(ROWS_XML, "NC", "Burke", sold=True)


def test_vendor_coded_loss_deeds_reach_the_instrument_list():
    summ = classify_rod_docs(_docs(), "cchs_rod")
    kept = {i["type"]: i for i in summ["instruments"]}
    assert {"TR/D", "COM/D", "SHF/D"} <= set(kept)
    assert kept["TR/D"]["inst_class"] == ic.TRUSTEE_DEED
    assert kept["COM/D"]["inst_class"] == ic.COMMISSIONER_DEED
    assert kept["SHF/D"]["inst_class"] == ic.SHERIFF_DEED
    assert (kept["SHF/D"]["book"], kept["SHF/D"]["page"]) == ("9001", "377")
    assert summ["kinds"]["TR/D"] == 2                         # two TR/D documents in the fixture


def test_the_deed_of_trust_is_still_counted_and_carries_no_loss_class():
    summ = classify_rod_docs(_docs(), "cchs_rod")
    dot = [i for i in summ["instruments"] if i["type"] == "D/T"]
    assert len(dot) == 1 and "inst_class" not in dot[0]
    assert summ["has_mortgage"] is True and summ["mortgage_count"] == 1
    # a completed foreclosure is a conveyance, not a lien
    assert summ["has_adverse_lien"] is False


def test_a_tax_deed_keeps_its_label_and_is_still_not_an_adverse_lien():
    """normalize_doc_type now returns 'TAX DEED' instead of 'DEED'. \\bTAX\\b would
    have started flagging every owner with a tax deed in his name as carrying an
    adverse lien; the deed conveys the parcel, it does not encumber it."""
    doc = RodDoc(county="Anderson", state="SC", doc_type=normalize_doc_type("TAX DEED"),
                 recorded_date=datetime(2021, 4, 2), book="8000", page="12")
    summ = classify_rod_docs([doc], "generic_rod")
    assert doc.doc_type == "TAX DEED"
    assert summ["has_adverse_lien"] is False and summ["adverse_types"] == []
    assert summ["instruments"][0]["inst_class"] == ic.TAX_DEED
    # a tax LIEN still is one
    lien = RodDoc(county="Anderson", state="SC", doc_type="TAX LIEN")
    assert classify_rod_docs([lien], "generic_rod")["has_adverse_lien"] is True


def test_distress_sale_flags_every_loss_spelling_and_nothing_else():
    for dt in ("TR/D", "COM/D", "SHF/D", "TRUSTEES DEED", "COMMISSIONERS DEED", "SHERIFFS DEED",
               "TAX DEED", "TRUSTEE'S DEED"):
        assert _is_distress_sale(None, dt), dt
    for dt in ("DEED", "D/T", "DEED OF TRUST", "S/TR", "WARRANTY DEED", ""):
        assert not _is_distress_sale(None, dt), dt
    assert _is_distress_sale(1.0, "DEED")                     # $1 sale, unchanged
