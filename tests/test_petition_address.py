"""Official Form 101 residence + county parser and the free-RECAP petition picker.

All names and addresses below are invented. The layouts are the two real text-layer
shapes CM/ECF petitions produce: a single combined "Number, Street, City, State &
ZIP Code" label, and the older split "Number Street" / "City State ZIP Code" labels.
"""
from __future__ import annotations

from types import SimpleNamespace

from foreclosure_scraper.petition_address import (
    apply_petition_address,
    candidate_from_search_hit,
    debtor_name_agrees,
    debtor_name_conflicts,
    parse_form101_text,
    petition_pdf_url,
    pick_petition_doc,
)

COMBINED_LAYOUT = """\
Debtor 1 Jane Q Example Case number (if known)
About Debtor 1: About Debtor 2 (Spouse Only in a Joint Case):
Your Employer
4.
Identification Number
(EIN), if any.
EIN EIN
5. Where you live If Debtor 2 lives at a different address:
123 Sample Court
Exampleton, NC 28000
Number, Street, City, State & ZIP Code Number, Street, City, State & ZIP Code
Lincoln
County County
If your mailing address is different from the one If Debtor 2's mailing address is different from yours, fill it
above, fill it in here. Note that the court will send any in here. Note that the court will send any notices to this
notices to you at this mailing address. mailing address.
99 Mailing Box Road
Elsewhere, NC 28999
Number, P.O. Box, Street, City, State & ZIP Code Number, P.O. Box, Street, City, State & ZIP Code
6. Why you are choosing Check one: Check one:
"""

SPLIT_LAYOUT = """\
Debtor 1 John Sample Placeholder Case number (if known)
About Debtor 1: About Debtor 2 (Spouse Only in a Joint Case):
4. Your Employer Identification
Number (EIN), if any.
EIN EIN
If Debtor 2 lives at a different address:
5. Where you live
456 Fictional Cir
Number Street Number Street
Samplevile, SC 29999-6017
City State ZIP Code City State ZIP Code
York
County County
If your mailing address is different from the one above,
fill it in here.
6. Why you are choosing this Check one:
"""

FORM_201 = """\
Official Form 201
Voluntary Petition for Non-Individuals Filing for Bankruptcy
Debtor's name Example Holdings LLC
Principal place of business 1 Business Way
"""


def test_combined_layout_reads_street_city_zip_county():
    r = parse_form101_text(COMBINED_LAYOUT)
    assert r["street"] == "123 Sample Court"
    assert (r["city"], r["state"], r["zip"]) == ("Exampleton", "NC", "28000")
    assert r["county"] == "Lincoln"
    assert r["debtor_name"] == "Jane Q Example"


def test_mailing_address_block_is_never_read_as_the_residence():
    r = parse_form101_text(COMBINED_LAYOUT)
    assert "Mailing" not in (r["street"] or "")
    assert r["city"] != "Elsewhere"


def test_split_label_layout_and_zip_plus_four_and_out_of_court_state():
    r = parse_form101_text(SPLIT_LAYOUT)
    assert r["street"] == "456 Fictional Cir"
    assert (r["city"], r["state"], r["zip"]) == ("Samplevile", "SC", "29999")
    assert r["county"] == "York"


def test_non_individual_petition_and_empty_text_return_none():
    assert parse_form101_text(FORM_201) is None
    assert parse_form101_text("") is None
    assert parse_form101_text(None) is None


def _rd(desc, available=True, fp="recap/gov.uscourts.ncwb.1/gov.uscourts.ncwb.1.1.0.pdf"):
    return {"short_description": desc, "is_available": available, "filepath_local": fp}


def test_pick_petition_requires_an_archived_copy_never_a_purchase():
    # metadata exists but CourtListener holds no PDF -> would need PACER -> never picked
    assert pick_petition_doc([_rd("Voluntary Petition (Chapter 7)", available=False)]) is None
    assert pick_petition_doc([_rd("Voluntary Petition (Chapter 7)", fp=None)]) is None
    got = pick_petition_doc([_rd("Voluntary Petition (Chapter 13) (atty)")])
    assert got is not None
    assert petition_pdf_url(got).startswith("https://storage.courtlistener.com/recap/")


def test_pick_petition_reads_the_title_not_the_clerk_notes_that_trail_it():
    long_desc = ("Voluntary Petition Under Chapter 13 - Filing Fee Amount $ 313 (Attachments: # 1 Exhibit "
                 "Business Entities) (Sample, Clerk)Modified on 3/4/2025 (xyz). SEE DEFECTIVE NOTICE 3. "
                 "(Entered: 03/04/2025)")
    assert pick_petition_doc([_rd(long_desc)]) is not None
    assert pick_petition_doc([_rd("Chapter 13 Plan,and Request for Valuation (Voluntary Petition) - Fee")]) is None


def test_pick_petition_skips_documents_that_only_mention_it():
    docs = [
        _rd("Chapter 13 Plan,and Request for Valuation of Security (Voluntary Petition filed)"),
        _rd("Means Test Calculation 122C-2 (Voluntary Petition)"),
        _rd("Personal Financial Management Course Certificate"),
    ]
    assert pick_petition_doc(docs) is None
    assert pick_petition_doc(None) is None


def test_candidate_from_search_hit_maps_docket_to_the_free_pdf():
    hit = {"docket_id": 111, "court_id": "ncmb",
           "recap_documents": [_rd("Personal Financial Management Course Certificate"),
                               _rd("Voluntary Petition (Chapter 7)")]}
    cand = candidate_from_search_hit(hit)
    assert cand["docket_id"] == 111 and cand["court"] == "ncmb"
    assert cand["doc_url"].startswith("https://storage.courtlistener.com/")
    assert candidate_from_search_hit({"docket_id": 1, "recap_documents": [
        _rd("Voluntary Petition (Chapter 7)", available=False)]}) is None
    assert candidate_from_search_hit({"recap_documents": [_rd("Voluntary Petition (Chapter 7)")]}) is None


def test_debtor_name_guard_needs_given_name_and_surname():
    assert debtor_name_agrees("Jane Q Example and John R Example", "Jane Q Example")
    assert not debtor_name_agrees("Jane Q Example", "Mary Other Person")
    assert not debtor_name_agrees("Jane Q Example", None)
    # a shared surname alone is not enough
    assert not debtor_name_agrees("Jane Q Example", "Zed Example")


def test_apply_fills_blanks_only_and_flags_state_mismatch():
    li = SimpleNamespace(raw={}, county=None, street_address=None, city=None,
                         state="NC", zip_code=None)
    parsed = parse_form101_text(SPLIT_LAYOUT)
    filled = apply_petition_address(li, parsed, document_url="https://storage.courtlistener.com/x.pdf",
                                    court_state="NC")
    assert li.county == "York" and li.street_address == "456 Fictional Cir"
    assert li.state == "NC"  # a set value is never overwritten
    assert "state" not in filled and "county" in filled
    ev = li.raw["bankruptcy_petition"]
    assert ev["residence_state"] == "SC" and ev["state_differs_from_court"] is True
    assert ev["kind"] == "residence_not_proof_of_ownership"


def test_apply_never_clobbers_an_existing_county():
    li = SimpleNamespace(raw={}, county="Polk", street_address=None, city=None,
                         state=None, zip_code=None)
    apply_petition_address(li, parse_form101_text(COMBINED_LAYOUT),
                           document_url="https://storage.courtlistener.com/y.pdf", court_state="NC")
    assert li.county == "Polk"
    assert li.raw["bankruptcy_petition"]["residence_county"] == "Lincoln"


def test_a_petition_for_a_different_debtor_is_never_applied():
    li = SimpleNamespace(raw={}, county=None, street_address=None, city=None,
                         state=None, zip_code=None)
    parsed = parse_form101_text(COMBINED_LAYOUT)  # debtor: Jane Q Example
    out = apply_petition_address(li, parsed, document_url="https://storage.courtlistener.com/z.pdf",
                                 court_state="NC", case_name="Mary Other Person")
    assert out == [] and li.county is None and "bankruptcy_petition" not in li.raw
    ok = apply_petition_address(li, parsed, document_url="https://storage.courtlistener.com/z.pdf",
                                court_state="NC", case_name="Jane Q Example and John R Example")
    assert "county" in ok and li.county == "Lincoln"


def test_unreadable_debtor_name_line_is_not_a_conflict():
    assert debtor_name_conflicts("Jane Q Example", None) is False
    assert debtor_name_conflicts("Jane Q Example", "Jane Q Example") is False
    assert debtor_name_conflicts("Jane Q Example", "Mary Other Person") is True
