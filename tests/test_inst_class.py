"""rod.inst_class: one canonical class for every spelling of a recorded deed.

Labels below are the ones the county dictionaries actually serve. Burke and
Lincoln were read from realestatesearch.asp on 2026-09-20 (see
fixtures/cchs_doctypes_*.html); Cleveland's are from the scoping doc.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.rod import inst_class as ic
from foreclosure_scraper.rod.inst_class import classify_instrument, is_deed_class, is_loss_class
from foreclosure_scraper.rod.models import DOC_BUCKETS, normalize_doc_type


@pytest.mark.parametrize("label,expected", [
    # CCHS vendor codes
    ("TR/D", ic.TRUSTEE_DEED),
    ("TR/DEED", ic.TRUSTEE_DEED),
    ("COM/D", ic.COMMISSIONER_DEED),
    ("COMM/D", ic.COMMISSIONER_DEED),
    ("COMM/DEED", ic.COMMISSIONER_DEED),
    ("SHF/D", ic.SHERIFF_DEED),
    # dictionary names, with and without the apostrophe
    ("TRUSTEES DEED", ic.TRUSTEE_DEED),
    ("Trustee's Deed", ic.TRUSTEE_DEED),
    ("COMMISSIONER&apos;S DEED", ic.COMMISSIONER_DEED),
    ("COMMISSIONERS DEED", ic.COMMISSIONER_DEED),
    ("SHERIFF DEED", ic.SHERIFF_DEED),
    ("SHERIFFS DEED", ic.SHERIFF_DEED),
    ("SHERIFF'S DEED", ic.SHERIFF_DEED),
    # full text from Aumentum, Logan, assessor cards
    ("TAX DEED", ic.TAX_DEED),
    ("SUBSTITUTE TRUSTEES DEED", ic.TRUSTEE_DEED),
    ("TRUSTEES DEED UPON SALE", ic.TRUSTEE_DEED),
    ("FORECLOSURE DEED", ic.TRUSTEE_DEED),
    ("DEED UNDER POWER OF SALE", ic.TRUSTEE_DEED),
    ("MASTER'S DEED", ic.MASTER_DEED),
    ("MASTER IN EQUITY", ic.MASTER_DEED),
    ("CLERK'S DEED", ic.COMMISSIONER_DEED),
])
def test_loss_labels(label, expected):
    assert classify_instrument(label) == expected
    assert is_loss_class(expected)


@pytest.mark.parametrize("label,expected", [
    ("QCD", ic.QUITCLAIM),
    ("QUIT CLAIM DEED", ic.QUITCLAIM),
    ("DEED, QUIT CLAIM", ic.QUITCLAIM),
    ("D/SEP", ic.DEED_OF_SEPARATION),
    ("M/SEP", ic.DEED_OF_SEPARATION),
    ("DEED OF SEPARATION", ic.DEED_OF_SEPARATION),
    ("ADM-DEED", ic.EXECUTOR_DEED),
    ("EXRX-DEED", ic.EXECUTOR_DEED),
    ("GDN DEED", ic.EXECUTOR_DEED),
    ("EXECUTOR'S DEED", ic.EXECUTOR_DEED),
    ("DEED OF DISTRIBUTION", ic.DISTRIBUTION_DEED),
    ("DEED", ic.DEED),
    ("C/D", ic.DEED),
    ("WARRANTY DEED", ic.DEED),
])
def test_conveyances_that_are_not_losses(label, expected):
    assert classify_instrument(label) == expected
    assert not is_loss_class(expected)
    assert is_deed_class(expected)


@pytest.mark.parametrize("label", [
    "D/T", "DEED OF TRUST", "CORRECTED DEED OF TRUST", "MORTGAGE DEED", "RELEASE DEED", "REL/D",
    "DEED OF SUBORDINATION", "TIMBER DEED", "CEMETERY DEED",
    # notices that precede a sale, not the conveyance after it
    "SUBSTITUTION TRUSTEE", "S/TR", "R/TR", "RESIGNATION OF TRUSTEE", "SUBSTITUTE TRUSTEE PRE-95",
    "REPORT OF COMMISSIONERS", "R/COM", "COMMISSION", "FCL", "LIS/P", "SAT", "", None,
])
def test_labels_that_must_not_classify(label):
    assert classify_instrument(label) == ic.OTHER
    assert not is_deed_class(classify_instrument(label))


def test_the_strongest_label_wins_when_a_row_carries_two():
    """normalize_doc_type flattened TAX DEED to DEED; the vendor code beside it
    still says what the instrument is."""
    assert classify_instrument("DEED", "TAX DEED") == ic.TAX_DEED
    assert classify_instrument("TR/D", "TRUSTEES DEED") == ic.TRUSTEE_DEED
    assert classify_instrument("DEED", None) == ic.DEED
    assert classify_instrument(None, None) == ic.OTHER


def test_loss_classes_are_exactly_the_five_the_scoping_doc_names():
    assert ic.LOSS_CLASSES == {ic.TRUSTEE_DEED, ic.COMMISSIONER_DEED, ic.SHERIFF_DEED,
                               ic.MASTER_DEED, ic.TAX_DEED}


# --- rod.models.normalize_doc_type (finding F2) --------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("TAX DEED", "TAX DEED"),
    ("SHERIFF DEED", "SHERIFF DEED"),
    ("SHERIFF'S DEED", "SHERIFF'S DEED"),
    ("SHERIFFS DEED", "SHERIFFS DEED"),
    ("MASTER'S DEED", "MASTER'S DEED"),
    ("TRUSTEE DEED", "TRUSTEE DEED"),
])
def test_normalize_no_longer_flattens_forced_sale_deeds_to_deed(raw, expected):
    """It used to return "DEED" for TAX DEED and SHERIFF DEED (shortest matching
    key), so the loss could not be told from a warranty deed afterwards."""
    assert normalize_doc_type(raw) == expected
    assert DOC_BUCKETS[expected] == "post_sale_deed"


def test_normalize_keeps_existing_behaviour():
    assert normalize_doc_type("Warranty Deed") == "DEED"
    assert normalize_doc_type("DEED OF TRUST SATISFACTION") == "DEED OF TRUST"
    assert normalize_doc_type("TRUSTEES DEED UPON SALE") == "TRUSTEES DEED UPON SALE"
    assert normalize_doc_type("TAX LIEN") == "TAX LIEN"
    assert normalize_doc_type(None) == "UNKNOWN"
    # vendor short codes stay as served; the classifier reads them
    assert normalize_doc_type("TR/D") == "TR/D"
