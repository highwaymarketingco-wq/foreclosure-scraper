"""probate_heir_buncombe v3 (2026-10-07): a death-index entry is the decedent's only when its FULL
given and middle names equal the owner's; the confirmed heirs-of-record verdict says roll_says_heirs.

The live re-check for the lawyer package found a Buncombe parcel titled "<FIRST> <MAIDEN NAME>
<LAST> (HEIRS)" confirmed from the DEATHS entry "<LAST>, <FIRST> MAE": first name, surname and the
middle INITIAL agreed (M and M), the middle NAME did not, and a better-fitting entry sat beside it.
The same shape is built here with made-up names: owner ROSALIND HARGROVE TREVELYAN, entries
"TREVELYAN, ROSALIND HELEN" / "... HOPE" (H and H by chance). Every test fails on v2.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.verification.fetch import form_key
from foreclosure_scraper.verification.verifiers import foreclosure_rod_buncombe as F
from foreclosure_scraper.verification.verifiers import probate_heir_buncombe as ph
from tests.test_verification_probate_heir import (
    DEATHS_PAGE, TODAY, Voters, _chain, _claim, _dgrid, _doc, _gis, _heir_row, _parcel, decide)

DEC = ("TREVELYAN", "ROSALIND", "H")
OWNER = "ROSALIND HARGROVE TREVELYAN HEIRS"


@pytest.fixture(autouse=True)
def _fresh_run_state():
    F._RUNS.clear()
    yield
    F._RUNS.clear()


def entry(n, given, year=2023, bp="110/717", **kw):
    name = f"TREVELYAN, {given}"
    return _doc(n, year=year, grantors=[name], matched=[name], bp=bp, **kw)


# ---------------------------------------------------------------------------
# reading the names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,want", [
    ("ROSALIND HARGROVE TREVELYAN (HEIRS)", ["ROSALIND", "HARGROVE"]),       # first-last, roll wording
    ("TREVELYAN (HEIRS) ROSALIND HARGROVE", ["ROSALIND", "HARGROVE"]),       # the county layer's order
    ("TREVELYAN ROSALIND HARGROVE", ["ROSALIND", "HARGROVE"]),
    ("Rosalind H Trevelyan", ["ROSALIND", "H"]),
    ("Rosalind Trevelyan Jr", ["ROSALIND"]),
    ("TREVELYAN, ROSALIND HARGROVE ESTATE", ["ROSALIND", "HARGROVE"]),
    ("SOMEONE ELSE ENTIRELY", None),                                         # not this person
    ("TREVELYAN MARGUERITE", None),                                          # the surname, another first name
])
def test_given_tokens(source, want):
    assert ph.given_tokens(source, DEC) == want


def test_given_tokens_keep_a_surname_particle_together():
    assert ph.given_tokens("VAN DOOREN ELIZABETH ADRIENNE", ("VAN DOOREN", "ELIZABETH", "A")) == \
        ["ELIZABETH", "ADRIENNE"]


@pytest.mark.parametrize("source,record,want", [
    (["ROSALIND", "HARGROVE"], ["ROSALIND", "HARGROVE"], "full"),
    (["ROSALIND", "HARGROVE"], ["ROSALIND", "HELEN"], "differs"),            # H and H by chance
    (["ROSALIND", "H"], ["ROSALIND", "HELEN"], "initial_only"),
    (["ROSALIND"], ["ROSALIND", "HELEN"], "initial_only"),                   # no middle on the claim
    (["ROSALIND", "HARGROVE"], ["ROSALIND"], "initial_only"),
    (["ROSALIND", "H"], ["ROSALIND", "M"], "differs"),
    (["ROSALIND", "HARGROVE", "LEE"], ["ROSALIND", "HARGROVE"], "initial_only"),
])
def test_name_agreement(source, record, want):
    assert ph.name_agreement(source, record) == want


def test_the_most_informative_source_decides():
    assert ph._agreement([["ROSALIND", "H"], ["ROSALIND", "HARGROVE"]], ["ROSALIND", "HELEN"]) == "differs"
    assert ph._agreement([["ROSALIND", "H"], ["ROSALIND", "HELEN"]], ["ROSALIND", "HELEN"]) == "full"
    assert ph._agreement([["ROSALIND", "H"]], ["ROSALIND", "HELEN"]) == "initial_only"


# ---------------------------------------------------------------------------
# the DEATHS index
# ---------------------------------------------------------------------------

NAMES = [["ROSALIND", "HARGROVE"]]


def test_an_entry_with_another_middle_name_is_not_the_decedent():
    """The lawyer-package case: the initials agree, the middle names do not."""
    g = _dgrid(entry(1, "ROSALIND HELEN"))
    assert ph.death_match(g, DEC, _claim())["match"] == "matched"                    # v2: claimed
    m = ph.death_match(g, DEC, _claim(), None, NAMES)
    assert m["match"] == "name_mismatch" and m["name_agreement"] == "differs"
    assert "recorded_year" not in m and "book_page" not in m                          # nothing of it is used
    both = _dgrid(entry(1, "ROSALIND HELEN"), entry(2, "ROSALIND HOPE", year=1983, bp="75/12"))
    m2 = ph.death_match(both, DEC, _claim(), None, NAMES)
    assert m2["match"] == "name_mismatch" and m2["name_mismatch_records"] == 2


def test_the_entry_whose_full_names_equal_is_the_decedent_even_beside_a_lookalike():
    g = _dgrid(entry(1, "ROSALIND HELEN"), entry(2, "ROSALIND HARGROVE", year=2019, bp="104/9"))
    assert ph.death_match(g, DEC, _claim())["match"] == "ambiguous"                  # v2: could not choose
    m = ph.death_match(g, DEC, _claim(), None, NAMES)
    assert m["match"] == "matched" and m["recorded_year"] == 2019 and m["book_page"] == "104/9"
    assert m["name_mismatch_records"] == 1


def test_an_initial_only_agreement_is_unproven_unless_the_switch_allows_it(monkeypatch):
    g = _dgrid(entry(1, "ROSALIND HELEN"))
    initials = [["ROSALIND", "H"]]
    m = ph.death_match(g, DEC, _claim(), None, initials)
    assert (m["match"], m["name_agreement"]) == ("name_mismatch", "initial_only")
    monkeypatch.setattr(ph, "DEATH_NAME_INITIALS_OK", True)
    assert ph.death_match(g, DEC, _claim(), None, initials)["match"] == "matched"
    assert ph.death_match(g, DEC, _claim(), None, NAMES)["match"] == "name_mismatch"      # 'differs' never stands


def test_no_name_source_keeps_the_initial_rules():
    """death_match called without the claim's spelled names behaves as v2 (nothing to compare)."""
    assert ph.death_match(_dgrid(entry(1, "ROSALIND HELEN")), DEC, _claim())["match"] == "matched"


def test_the_public_death_evidence_carries_the_agreement_but_no_name():
    ev = ph.public_evidence("unconfirmed", {"death": {"match": "name_mismatch", "name_agreement": "differs",
                                                      "name_mismatch_records": 2, "searched": 1}})
    assert ev["death"] == {"match": "name_mismatch", "name_agreement": "differs",
                           "name_mismatch_records": 2, "searched": 1}


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------

def test_a_name_mismatched_death_entry_leaves_heirs_of_record_unconfirmed():
    v, ev = decide(_parcel(OWNER), death={"match": "name_mismatch", "name_agreement": "differs"},
                   chain=_chain(), dec=DEC)
    assert (v, ev["reason"], ev["transfer"]["category"]) == \
        ("unconfirmed", "death_entry_name_mismatch", "heirs_of_record")
    assert ev["owner_relation"] == "heirs_of_record"          # the roll fact stays in the evidence
    v2, ev2 = decide(_parcel("TREVELYAN ROSALIND HARGROVE"), death={"match": "name_mismatch"}, dec=DEC)
    assert (v2, ev2["reason"]) == ("unconfirmed", "death_entry_name_mismatch")


def test_a_confirmed_heirs_of_record_verdict_says_the_roll_says_heirs():
    matched = {"match": "matched", "basis": "middle_agrees", "recorded_year": 2019, "book_page": "104/9"}
    v, ev = decide(_parcel(OWNER), death=matched, chain=_chain(), dec=DEC)
    assert (v, ev["reason"], ev["decided_by"]) == ("confirmed", "roll_says_heirs", "death_record_and_heirs_of_record")
    v2, ev2 = decide(_parcel("TREVELYAN ROSALIND HARGROVE"), death=matched, chain=None, dec=DEC)
    assert v2 == "confirmed" and "reason" not in ev2           # titled to the decedent: no heirs wording


def test_a_name_mismatched_entry_is_never_used_for_timing_or_to_refute():
    """No death year (so no (A)/(R1) timing) and (R2) needs the record NOT found."""
    a = _parcel("TREVELYAN ROSALIND HARGROVE", SubName="LAUREL PARK", SubLot="7")
    dot = _doc(4, date="2026-09-30", type_="DEED OF TRUST", grantors=["TREVELYAN, ROSALIND HARGROVE"],
               grantees=["FIRST LENDER BANK"], matched=["TREVELYAN, ROSALIND HARGROVE"], bp="6630/1",
               desc="LOT 7 LAUREL PARK")
    claim = _claim(death_by="2026-05-01", dates={"first_seen": "2026-05-01"})
    assert decide(a, death={"match": "not_found"}, chain=_chain(dot), claim=claim, dec=DEC)[0] == "refuted"
    v, ev = decide(a, death={"match": "name_mismatch"}, chain=_chain(dot), claim=claim, dec=DEC)
    assert (v, ev["reason"]) == ("unconfirmed", "death_entry_name_mismatch")


# ---------------------------------------------------------------------------
# verify() end to end
# ---------------------------------------------------------------------------

def deaths_page(given):
    return (DEATHS_PAGE.replace("PELLWORTH, ODESSA MAE", f"TREVELYAN, {given}")
            .replace("PELLWORTH, INFANT MALE", "TREVELYAN, INFANT MALE").replace("PELLWORTH, ARLO", "TREVELYAN, ARLO"))


def responses(owner_now, given):
    return {F.gis_url_pin("970000000100000"): _gis(owner_now),
            F.SEARCH_URL: "<html><body><div id='ucSrchNames'>search</div></body></html>",
            form_key(F.SEARCH_URL, ph.death_body("TREVELYAN", "ROSALIND")): deaths_page(given),
            form_key(F.SEARCH_URL, F.name_body("TREVELYAN", "ROSALIND")):
                "<html><span>Your search returned <strong> 0</strong> results</span></html>"}


def run(row, client):
    return asyncio.run(ph.verify(row, client, today=TODAY))


def test_verify_a_chance_initial_match_is_unconfirmed_with_one_death_search():
    c = Voters(responses(OWNER, "ROSALIND HELEN"))
    res = run(_heir_row(OWNER), c)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "death_entry_name_mismatch"
    assert res.evidence["death"]["match"] == "name_mismatch" and res.evidence["death"]["name_agreement"] == "differs"
    assert res.evidence["owner_relation"] == "heirs_of_record"
    # the reading that found same-name records is not retried in the other order (v2 never
    # needed to: a match stopped the loop; a name_mismatch must stop it too)
    assert form_key(F.SEARCH_URL, ph.death_body("TREVELYAN", "ROSALIND")) in c.asked
    assert form_key(F.SEARCH_URL, ph.death_body("ROSALIND", "TREVELYAN")) not in c.asked
    blob = str(res.to_dict()).upper()
    for tok in ("TREVELYAN", "ROSALIND", "HARGROVE", "HELEN"):
        assert tok not in blob, tok


def test_verify_the_full_name_entry_confirms_and_says_the_roll_says_heirs():
    res = run(_heir_row(OWNER), Voters(responses(OWNER, "ROSALIND HARGROVE")))
    assert res.verdict == "confirmed" and res.evidence["reason"] == "roll_says_heirs"
    assert res.evidence["death"]["match"] == "matched"
    assert res.evidence["decided_by"] == "death_record_and_heirs_of_record"
