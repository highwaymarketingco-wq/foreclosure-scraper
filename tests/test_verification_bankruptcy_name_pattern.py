"""bankruptcy_stay v4: a NAME PATTERN is a reason not to refute.

The positional matcher compares first and last name in their places. A woman who filed under a
married name and owns under another (the debtor's first name, and the debtor's spelled-out MIDDLE
name as the owner's SURNAME) and a person who goes by the middle name (the debtor's surname and
the debtor's middle name as the owner's FIRST name) are therefore called "a different person", and
a refuted verdict removes the bankruptcy signal from the lead. The independent live re-check of
2026-10-06 held 36 of 42 refuted entries and found 2 plausibly the same person and 4 undecidable,
all of these shapes. v4: when a pattern fires in a court that can cover the property (and the
owner's mailing state, where the board knows it, is the court's state) the verdict is
unconfirmed, reason name_pattern_possible_same_person, so the claim keeps scoring.

Every name, docket number and id below is made up; the CourtListener search hit is the real shape
(tests/test_verification_bankruptcy_identity.py builds it the same way). No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import bankruptcy_stay as b

TODAY = date(2026, 10, 6)

# made-up debtors in the shapes the real board rows had
MAIDEN_DEBTOR = "Marlene Rowan Pettibone"                       # owner ROWAN, MARLENE
MIDDLE_DEBTOR = "Gideon Maxwell Thornbury"                      # owner THORNBURY, MAXWELL
JOINT_DEBTORS = "Elias Corbin Vance and Rosalind Faye Garrity"  # owner CORBIN, ROSALIND
FIXTURE_NAMES = ("Pettibone", "Thornbury", "Rowan", "Maxwell", "Marlene", "Gideon", "Corbin",
                 "Rosalind", "Garrity", "Vance", "Elias")


def _hit(did, court, dn, case):
    """The CourtListener search hit of one made-up docket (the real shape)."""
    return [(b.SEARCH_BY_ID.format(id=did), json.dumps({
        "count": 1, "next": None, "previous": None, "results": [{
            "caseName": case, "case_name_full": "", "chapter": "13", "court_id": court,
            "dateFiled": "2026-07-10", "dateTerminated": None, "docketNumber": dn,
            "docket_absolute_url": f"/docket/{did}/x/", "docket_id": did, "party": [case]}]}))]


def _row(owner, court, case, *, state="NC", county="Buncombe", mailing=None, defendant=None,
         did=76100001, dn="26-30001"):
    raw = {"bankruptcy": {"court": court, "case_name": case, "docket_number": dn,
                          "absolute_url": f"/docket/{did}/x/", "match_strategy": "strict_subset"}}
    if mailing:
        raw["owner_mailing"] = dict(mailing)
    return {"state": state, "county": county, "listing_type": "tax_lien", "owner_name": owner,
            "defendant": owner if defendant is None else defendant,
            "street_address": "1 MAIN ST", "parcel_id": "1111-11-1111-00000", "raw": raw}


def run(row, court, case, *, did=76100001, dn="26-30001"):
    f = ReplayFetcher(dict(_hit(did, court, dn, case)))
    return asyncio.run(b.verify(row, f, today=TODAY)), f


def _no_names(ev):
    blob = json.dumps(ev).lower()
    for n in FIXTURE_NAMES:
        assert n.lower() not in blob, n
    assert "url" not in ev and "lookup" not in ev and "claimed" not in ev and "parties" not in ev


def _unconfirmed_by_pattern(r, pattern, across=False):
    assert r.verdict == "unconfirmed", r.evidence
    ev = r.evidence
    assert ev["reason"] == "name_pattern_possible_same_person"
    assert ev["name_pattern"] == pattern
    assert ev.get("name_pattern_across_debtors", False) is across
    assert ev["owner_match"] == "none"
    assert ev["court"] and ev["court_state"] == "NC"
    assert "decided_by" not in ev and "status" not in ev       # the case's status is not read
    _no_names(ev)


# ---------------------------------------------------------------------------
# the pure rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("owner", [
    "ROWAN, MARLENE",             # comma: surname, first
    "ROWAN MARLENE K",            # the county roll: capitals, surname first
    "Marlene K Rowan",            # a court-style Title Case name
    "Rowan Marlene K",            # Title Case roll entry, surname first (order read both ways)
    "ROWAN, MARLENA",             # one edit apart on the first name (4+ letters)
])
def test_maiden_name_pattern_fires(owner):
    """The owner has the debtor's first name; the debtor's middle name is the owner's surname."""
    assert b.name_pattern(owner, MAIDEN_DEBTOR) == {"pattern": "maiden_name", "across_debtors": False}


@pytest.mark.parametrize("owner", [
    "THORNBURY, MAXWELL",
    "THORNBURY MAXWELL J",
    "Maxwell J Thornbury",
    "Thornbury Maxwell J",
])
def test_middle_as_first_pattern_fires(owner):
    """The owner has the debtor's surname and the debtor's middle name as the first name."""
    assert b.name_pattern(owner, MIDDLE_DEBTOR) == {"pattern": "middle_as_first",
                                                    "across_debtors": False}


def test_a_second_middle_name_counts_and_a_jr_does_not_hide_the_pattern():
    assert b.name_pattern("THORNBURY, ROCKET", "Gideon Maxwell Rocket Thornbury, Jr.")["pattern"] \
        == "middle_as_first"
    assert b.name_pattern("THORNBURY MAXWELL JR", "Gideon Maxwell Thornbury, Jr.")["pattern"] \
        == "middle_as_first"


def test_joint_filers_interleave_is_a_maiden_pattern_across_debtors():
    """The owner's first name is one filer's, the owner's surname the OTHER filer's middle name."""
    assert b.name_pattern("CORBIN ROSALIND P", JOINT_DEBTORS) == {"pattern": "maiden_name",
                                                                  "across_debtors": True}
    # within ONE filer the same shape is not 'across'
    assert b.name_pattern("CORBIN ELIAS P", JOINT_DEBTORS)["across_debtors"] is False


def test_the_joint_filer_phantom_is_not_a_pattern():
    """First name of debtor 1 + surname of debtor 2 (no middle name involved) is the phantom
    production's matcher exists to reject: nothing here softens it."""
    assert b.name_pattern("GARRITY, ELIAS", JOINT_DEBTORS) is None


@pytest.mark.parametrize("owner,case", [
    ("ROWAN, MARLENE", "Marlene Pettibone"),                      # first name only, no middle at all
    ("FENWICK, MARLENE", MAIDEN_DEBTOR),                          # first name only
    ("PETTIBONE, DOROTHEA", MAIDEN_DEBTOR),                       # same surname only
    ("THORNBURY, DOROTHEA", MIDDLE_DEBTOR),                       # same surname only
    ("ROWAN, DOROTHEA", MAIDEN_DEBTOR),                           # the middle name alone
    ("PETTIBONE MARLENE K", MAIDEN_DEBTOR),                       # a plain middle-name conflict
    ("THORNBURY GIDEON P", MIDDLE_DEBTOR),                        # a plain middle-name conflict
    ("RO, MARLENE", "Marlene Ro Pettibone"),                      # a 2-letter middle is no name
    ("R, MARLENE", "Marlene R Pettibone"),                        # an initial is no name
    ("THORNBURY, M", "Gideon M Thornbury"),
    ("ROWAN, MARLENE", "Rowan Marlene Holdings LLC"),             # an entity debtor
    ("", MAIDEN_DEBTOR), (None, MAIDEN_DEBTOR), ("ROWAN, MARLENE", ""), ("ROWAN, MARLENE", None),
])
def test_no_pattern_without_both_names(owner, case):
    assert b.name_pattern(owner, case) is None


def test_a_surname_read_as_a_first_name_is_not_a_typo_of_one():
    """An ALL-CAPS roll entry is surname first. Read the other way round ('WILLIAMS' as a first
    name, one edit from 'William') it would match a debtor's first and middle names; the other
    order is read with exact first names only."""
    assert b.owner_readings("RANDALLS JOSIAH JR") == [("RANDALLS", "JOSIAH", True),
                                                      ("JOSIAH", "RANDALLS", False)]
    assert b.owner_readings("Randalls Josiah Jr") == [("JOSIAH", "RANDALLS", True),
                                                      ("RANDALLS", "JOSIAH", False)]
    assert b.name_pattern("RANDALLS JOSIAH JR", "Randall Josiah Quincy, Jr.") is None
    # exact first names in the other order still count (the county roll gave the tokens as
    # SURNAME FIRST MIDDLE, the debtor is FIRST MIDDLE LAST: 'TRAVIS RONALD EDWIN')
    assert b.name_pattern("PRESCOTT ROYCE EDMUND JR", "Prescott Edmund Lowe")["pattern"] == "maiden_name"


def test_first_name_tolerance_is_one_edit_on_four_letters_or_more():
    assert b._same_given("MARLENE", "MARLENA") and b._same_given("MARLENE", "MARLEN")
    assert b._same_given("JON", "JON") and not b._same_given("JON", "JAN")     # 3 letters: exact only
    assert b._same_given("JOHN", "JON")                                        # the longer has 4
    assert not b._same_given("MARLENE", "MARLINA")                             # two edits
    assert not b._same_given("MARLENE", "MARLENA", typo_ok=False)
    assert not b._same_given("M", "M")                                         # an initial


def test_debtor_segments_split_joint_filers_aliases_and_drop_entities():
    assert b.debtor_segments(JOINT_DEBTORS) == [("ELIAS", ("CORBIN",), "VANCE"),
                                                ("ROSALIND", ("FAYE",), "GARRITY")]
    assert b.debtor_segments("Gideon Maxwell Thornbury, Jr.") == [("GIDEON", ("MAXWELL",), "THORNBURY")]
    assert b.debtor_segments("Gideon Thornbury a/k/a Gid Maxwell Thornbury") == [
        ("GIDEON", (), "THORNBURY"), ("GID", ("MAXWELL",), "THORNBURY")]
    assert b.debtor_segments("Thornbury Maxwell Holdings LLC") == []
    assert b.debtor_segments("Thornbury") == [] and b.debtor_segments(None) == []


def test_row_name_pattern_reads_every_co_owner_and_every_board_name():
    claim = {"from": "raw.bankruptcy"}
    row = _row("FAIRBANKS WALTER;ROWAN MARLENE K", "ncwb", MAIDEN_DEBTOR)
    hit = b.row_name_pattern(row, claim, MAIDEN_DEBTOR)
    assert hit == {"pattern": "maiden_name", "across_debtors": False, "field": "owner_name"}
    # the defendant is a board name too, and a same-debtor hit wins over an across-debtors one
    row = _row("CORBIN ROSALIND P", "ncwb", JOINT_DEBTORS, defendant="CORBIN ELIAS P")
    assert b.row_name_pattern(row, claim, JOINT_DEBTORS) == {
        "pattern": "maiden_name", "across_debtors": False, "field": "defendant"}
    assert b.row_name_pattern(_row("FAIRBANKS WALTER", "ncwb", MAIDEN_DEBTOR), claim,
                              MAIDEN_DEBTOR) is None


# ---------------------------------------------------------------------------
# which court counts
# ---------------------------------------------------------------------------

def test_owner_mailing_state_reads_the_structured_fields_then_the_mailing_line():
    def row(**raw):
        return {"raw": raw}
    assert b.owner_mailing_state(row(owner_mailing={"mail_state": "nc"})) == "NC"
    assert b.owner_mailing_state(row(owner_mailing={"state": "SC"})) == "SC"
    assert b.owner_mailing_state(row(skip_trace={"mail_state": "GA"})) == "GA"
    assert b.owner_mailing_state(row(owner_mailing={"mailing": "15 CEDAR CIR ASHEVILLE NC 28804"})) == "NC"
    assert b.owner_mailing_state(row(skip_trace={"owner_mailing_address": "9 OAK ST PICKENS SC 29671-0000"})) == "SC"
    assert b.owner_mailing_state(row(gis={"mailing": "PO BOX 12 CROUSE NC 28033"})) == "NC"
    # a street suffix or a court is not a state: a state code needs a ZIP behind it
    assert b.owner_mailing_state(row(owner_mailing={"mailing": "12 ELM CT"})) is None
    assert b.owner_mailing_state(row(owner_mailing={"mailing": "4138 SAMPLE RD"})) is None
    assert b.owner_mailing_state(row(owner_mailing={"mail_state": "ZZ"})) is None
    assert b.owner_mailing_state({"raw": None}) is None and b.owner_mailing_state({}) is None


def test_pattern_court_ok():
    ok = b.pattern_court_ok
    assert ok("ncwb", "NC", "NC", "Buncombe", "NC")
    assert ok("ncwb", "NC", "NC", "Buncombe", None)                   # mailing state unknown: no veto
    assert ok("ncwb", "NC", "NC", "Nowhere", "NC")                    # county not in the table: no claim
    assert not ok("ncmb", "NC", "NC", "Buncombe", "NC")               # a district that cannot cover it
    assert not ok("ncwb", "NC", "SC", "Greenville", "SC")             # a court in the other state
    assert not ok("scb", "SC", "NC", "Buncombe", "NC")
    assert not ok("ncwb", "NC", "NC", "Buncombe", "GA")               # the owner mails from elsewhere
    assert ok("ncmb", "NC", "NC", "Moore", "NC") and not ok("ncwb", "NC", "NC", "Moore", "NC")


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------

def test_maiden_pattern_in_the_right_district_is_unconfirmed_not_refuted():
    """v3: refuted, decided_by no_positional_match. v4: unconfirmed; the claim keeps scoring."""
    row = _row("ROWAN, MARLENE", "ncwb", MAIDEN_DEBTOR,
               mailing={"mailing": "15 CEDAR CIR ASHEVILLE NC 28804", "mail_state": "NC"})
    r, f = run(row, "ncwb", MAIDEN_DEBTOR)
    _unconfirmed_by_pattern(r, "maiden_name")
    assert f.asked == [b.SEARCH_BY_ID.format(id=76100001)]            # the docket entries are not read


def test_middle_as_first_pattern_in_the_right_district_is_unconfirmed():
    row = _row("THORNBURY MAXWELL J", "ncwb", MIDDLE_DEBTOR, county="McDowell")
    r, f = run(row, "ncwb", MIDDLE_DEBTOR)
    _unconfirmed_by_pattern(r, "middle_as_first")                     # no mailing state known: fires


def test_joint_filers_pattern_is_unconfirmed_and_says_it_is_across_debtors():
    row = _row("CORBIN ROSALIND P", "scb", JOINT_DEBTORS, state="SC", county="Florence",
               mailing={"mail_state": "SC"})
    r, _ = run(row, "scb", JOINT_DEBTORS)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "name_pattern_possible_same_person"
    assert r.evidence["name_pattern"] == "maiden_name"
    assert r.evidence["name_pattern_across_debtors"] is True
    assert r.evidence["court_state"] == "SC"
    _no_names(r.evidence)


def test_a_listing_row_s_snapped_parcel_owner_is_read_the_same_way():
    """A listing-type filing: the owner of record comes from the parcel the filing was snapped to
    (an ALL-CAPS roll entry, tokens in either order)."""
    row = {"state": "NC", "county": "Lincoln", "listing_type": "bankruptcy", "owner_name": MIDDLE_DEBTOR,
           "defendant": MIDDLE_DEBTOR, "street_address": "9 OLD RD", "parcel_id": "3612658974",
           "case_number": "26-30002", "source_url": "https://www.courtlistener.com/docket/76100002/x/",
           "raw": {"courtlistener": {"court": "ncwb"}, "owner_mismatch": {
               "defendant_surname": "thornbury", "snapped_owner": "GIDEON PRESCOTT MAXWELL JR"}}}
    r, _ = run(row, "ncwb", MIDDLE_DEBTOR, did=76100002, dn="26-30002")
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "name_pattern_possible_same_person"
    assert r.evidence["name_pattern"] == "maiden_name"
    assert r.evidence["match_field"] == "owner_mismatch.snapped_owner"


@pytest.mark.parametrize("owner,case", [
    ("ROWAN, MARLENE", MAIDEN_DEBTOR),
    ("THORNBURY, MAXWELL", MIDDLE_DEBTOR),
    ("CORBIN, ROSALIND", JOINT_DEBTORS),
])
def test_the_pattern_never_fires_when_the_court_cannot_cover_the_property(owner, case):
    """Each pattern needs a court that holds the county (and is in the row's state): a district
    that cannot cover Buncombe, a court of the other state, stay refuted exactly as before."""
    assert b.name_pattern(owner, case) is not None                    # the names alone do line up
    for court, state, county, why in [("ncmb", "NC", "Buncombe", "wrong NC district"),
                                      ("nceb", "NC", "Buncombe", "wrong NC district"),
                                      ("ncwb", "SC", "Greenville", "NC court, SC property"),
                                      ("scb", "NC", "Buncombe", "SC court, NC property")]:
        r, _ = run(_row(owner, court, case, state=state, county=county), court, case)
        assert r.verdict == "refuted", why
        assert r.evidence["decided_by"] == "no_positional_match", why
        assert "name_pattern" not in r.evidence and "reason" not in r.evidence, why
        _no_names(r.evidence)


def test_the_pattern_never_fires_when_the_owner_mails_from_another_state():
    """A court that covers the county, but the owner's mailing address is out of the court's state."""
    row = _row("ROWAN, MARLENE", "ncwb", MAIDEN_DEBTOR, mailing={"mailing": "5 PINE RD ATLANTA GA 30301"})
    assert b.name_pattern("ROWAN, MARLENE", MAIDEN_DEBTOR) is not None
    r, _ = run(row, "ncwb", MAIDEN_DEBTOR)
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "no_positional_match"
    # the same owner mailing from inside the state fires
    row = _row("ROWAN, MARLENE", "ncwb", MAIDEN_DEBTOR, mailing={"mailing": "5 PINE RD ASHEVILLE NC 28801"})
    r, _ = run(row, "ncwb", MAIDEN_DEBTOR)
    assert r.verdict == "unconfirmed"


def test_a_true_middle_name_conflict_stays_refuted():
    """Same first and last name, a different spelled-out middle: a different person with the same
    name. Neither pattern is anywhere in it."""
    row = _row("PETTIBONE MARLENE K", "ncwb", MAIDEN_DEBTOR)
    assert b.name_pattern("PETTIBONE MARLENE K", MAIDEN_DEBTOR) is None
    r, _ = run(row, "ncwb", MAIDEN_DEBTOR)
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "middle_conflict"
    assert (r.evidence["owner_middle_initial"], r.evidence["debtor_middle_initials"]) == ("K", ["R"])
    _no_names(r.evidence)


@pytest.mark.parametrize("owner,case,why", [
    ("FENWICK, MARLENE", MAIDEN_DEBTOR, "first name only"),
    ("ROWAN, MARLENE", "Marlene Pettibone", "first name only, the caption has no middle"),
    ("PETTIBONE, DOROTHEA", MAIDEN_DEBTOR, "same surname only"),
    ("THORNBURY, DOROTHEA", MIDDLE_DEBTOR, "same surname only"),
    ("GARRITY, ELIAS", JOINT_DEBTORS, "the joint-filer phantom"),
])
def test_first_name_only_and_surname_only_stay_refuted(owner, case, why):
    assert b.name_pattern(owner, case) is None, why
    r, f = run(_row(owner, "ncwb", case), "ncwb", case)
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "no_positional_match", why
    assert "name_pattern" not in r.evidence
    assert f.asked == [b.SEARCH_BY_ID.format(id=76100001)]
    _no_names(r.evidence)


def test_an_entity_debtor_is_unchanged():
    case = "Rowan Marlene Holdings LLC"
    assert b.name_pattern("ROWAN, MARLENE", case) is None and b.debtor_segments(case) == []
    r, _ = run(_row("ROWAN, MARLENE", "ncwb", case), "ncwb", case)
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "no_positional_match"
    assert r.evidence["debtor_count"] == 1 and "name_pattern" not in r.evidence


def test_a_plain_match_never_reaches_the_pattern_rule():
    """The pattern only runs when the plain match says none or conflict: a first + last match
    (a debtor who is the owner) is decided as before, here a confirmed-or-unconfirmed path that
    never carries a name_pattern."""
    row = _row("PETTIBONE, MARLENE", "ncwb", MAIDEN_DEBTOR)
    r, _ = run(row, "ncwb", MAIDEN_DEBTOR)
    assert r.evidence["owner_match"] == "unverified" and "name_pattern" not in r.evidence
    assert b.name_pattern("PETTIBONE, MARLENE", MAIDEN_DEBTOR) is None


# ---------------------------------------------------------------------------
# what is published
# ---------------------------------------------------------------------------

def test_the_pattern_is_published_without_names():
    row = _row("ROWAN, MARLENE", "ncwb", MAIDEN_DEBTOR)
    r, _ = run(row, "ncwb", MAIDEN_DEBTOR)
    ev = dict(r.evidence)
    assert set(ev) == {"reason", "name_pattern", "owner_match", "match_field", "compared_fields",
                       "claimed_from", "court", "court_state"}
    assert b.public_evidence("unconfirmed", ev) == ev                   # idempotent
    # the working evidence the verifier builds carries the person's name and the caption; the
    # whitelist drops both
    working = {"reason": "name_pattern_possible_same_person", "name_pattern": "middle_as_first",
               "name_pattern_across_debtors": True, "owner_match": "none", "court": "ncwb",
               "debtor_case_name": MIDDLE_DEBTOR, "parties": [MIDDLE_DEBTOR],
               "match": {"field": "owner_name", "person": "THORNBURY, MAXWELL",
                         "per_field": {"owner_name": {"name": "THORNBURY, MAXWELL"}}}}
    pub = b.public_evidence("unconfirmed", working)
    assert pub["name_pattern"] == "middle_as_first" and pub["name_pattern_across_debtors"] is True
    _no_names(pub)


def test_version_is_v4_and_the_reason_is_a_published_constant():
    assert b.VERSION == "v4"
    assert b.NAME_PATTERN_REASON == "name_pattern_possible_same_person"
