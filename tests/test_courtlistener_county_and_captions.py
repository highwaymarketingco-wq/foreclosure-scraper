"""CourtListener county attribution and adversary captions (measured 2026-10-06).

A bankruptcy docket's case name is the DEBTOR'S name, not an address.
`_county_from_text` used to take any KNOWN_CITIES word found anywhere in it, as a
plain substring, and return that town's county. Measured on the published board
(147 national.courtlistener_bankruptcy rows whose county came from that
function): 123 matched a whole word in a PERSON's name (a surname or given name
equal to a town or county: Wilson, Marion, Jackson, Clinton, Charlotte, ...),
15 matched inside a longer word (a trustee's surname containing "Anderson"), and
only 3 were an organization named for its town. 110 of the 147 carried no street
or parcel, so their county was nothing but that word, and 34 carried a parcel
pinned at that wrong county's point.

The same function is imported by courtlistener_adversary and courtlistener_civil.

The bankruptcy scraper also published true adversary-proceeding captions
("<Plaintiff> v. <Defendant>") as debtor petitions (110 of 4,779 published rows).

Every name below is invented.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.scrapers.national import courtlistener_adversary as ADV
from foreclosure_scraper.scrapers.national import courtlistener_civil as CIV
from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (
    CourtListenerBankruptcy,
    _county_from_text,
    _is_adversary_caption,
    _is_organization,
    _split_caption,
)


# ---------------------------------------------------------------------------
# _county_from_text: a person's name never yields a county
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,name", [
    # surname equal to a county / town name
    ("NC", "Orla Q. Marshall"),
    ("NC", "Dessa Wilson Tuck"),
    ("NC", "Prentice Jackson"),
    ("SC", "Corbin Anderson"),
    ("SC", "In re Ardith Belton"),
    # given name equal to a town
    ("NC", "Clayton Fenwick"),
    ("NC", "Charlotte Ann Pell"),
    ("NC", "Troy Mavis Holt"),
    ("NC", "Marion Dale Quist"),
    # middle / maiden name of one joint filer
    ("NC", "Roland Graham Pike and Maris Ann Pike"),
    ("NC", "Elias Ray Voss and Corinne Faye Newton Voss"),
    # a suffix does not make it an organization
    ("NC", "Clayton Fenwick, Jr."),
    ("NC", "Wendell Union III"),
])
def test_a_person_never_gets_a_county_from_their_name(state, name):
    assert _county_from_text(name, state) is None


@pytest.mark.parametrize("name", [
    # the town word sits INSIDE a longer word: never a match, for a person
    # (a surname that merely contains a town), a trustee, or an organization
    "Hollis Vanderson",
    "Evander Bingraham",
    "Wanda Merclinton",
    "Vanderson Holdings, LLC",
    "Merclinton Roofing Inc",
])
def test_a_town_inside_a_longer_word_is_never_a_match(name):
    assert _county_from_text(name, "NC") is None
    assert _county_from_text(name, "SC") is None


def test_a_name_without_corporate_form_evidence_is_treated_as_unknown():
    # no LLC/Inc/Corp/Ltd marker: could be a person, a family trust or a sole
    # proprietor. Unsure -> None.
    assert _county_from_text("Raleigh", "NC") is None
    assert _county_from_text("Raleigh Family Trust", "NC") is None
    assert _county_from_text("Estate of Maris Raleigh", "NC") is None
    assert _county_from_text("Raleigh Plumbing", "NC") is None
    # bare "Co" / "Pa" are real given names, not corporate-form markers
    assert _county_from_text("Co Nguyen of Gastonia", "NC") is None
    assert _county_from_text("Pa Vang Gastonia", "NC") is None


# ---------------------------------------------------------------------------
# _county_from_text: an organization named for its town keeps a county
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,name,county", [
    ("NC", "Acme Widgets of Raleigh, Inc.", "Wake"),
    ("NC", "In re: Acme Widgets of Raleigh, Inc.", "Wake"),
    ("NC", "Raleigh Hotel Partners, LLC", "Wake"),
    ("NC", "Plum Spa Charlotte, Inc.", "Mecklenburg"),
    ("NC", "Gastonia Hardware Co.", "Gaston"),
    ("NC", "Acme Dental, P.A. of Gastonia", "Gaston"),
    ("NC", "Winston-Salem Tire Corp", "Forsyth"),
    ("NC", "Bluebird Auto of Whiteville Ltd", "Columbus"),
    # state-scoped: the same word resolves inside the docket's own state
    ("NC", "Acme Widgets of Clinton LLC", "Sampson"),
    ("SC", "Acme Widgets of Clinton LLC", "Laurens"),
    # a multi-word town, and a nested one that agrees with itself
    ("SC", "Plum Spa North Charleston, LLC", "Charleston"),
])
def test_an_organization_named_for_its_town_keeps_the_county(state, name, county):
    assert _county_from_text(name, state) == county


def test_organization_with_two_disagreeing_towns_is_none():
    assert _county_from_text("Raleigh Charlotte Holdings, LLC", "NC") is None


def test_is_organization_is_positive_evidence_only():
    for name in ("Acme LLC", "Acme L.L.C.", "Acme, Inc.", "Acme Corp", "Acme Corporation",
                 "Acme Company", "Acme Ltd", "Acme Limited", "Acme LP", "Acme L.L.P.",
                 "Acme PLLC", "Acme Co.", "Acme P.A.", "Acme P.C."):
        assert _is_organization(name), name
    for name in ("Mira V. Quill", "Roland Graham Pike", "Co Nguyen", "Pa Vang",
                 "Raleigh Family Trust", "Estate of Maris Pike", "Acme Plumbing"):
        assert not _is_organization(name), name


# ---------------------------------------------------------------------------
# _county_from_text: a two-party caption never yields a county
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caption", [
    "Acme Widgets of Raleigh, Inc. v. Pat Doe",       # org party, debtor unknown
    "Bank of Charlotte v. Jane Roe",                   # the civil-feed shape
    "Vale, Trustee v. Acme Funding LLC",
    "Washington v. Acme Servicing, LLC",
    "Pat Doe vs. Acme Widgets of Raleigh, Inc.",
])
def test_a_two_party_caption_never_yields_a_county(caption):
    assert _is_adversary_caption(caption)
    assert _county_from_text(caption, "NC") is None


def test_adversary_caption_detector_is_case_sensitive():
    # CourtListener writes the connector in lower case; an upper-case "V." is a
    # middle initial. 6 of 4,779 published debtor names carry one.
    assert _is_adversary_caption("Taylor v. Honeycutt")
    assert _is_adversary_caption("Batt vs. Cole")
    assert not _is_adversary_caption("Mira V. Quill")
    assert not _is_adversary_caption("Alan V. Quill and Rene V. Quill")
    assert not _is_adversary_caption("In re Mira V. Quill")
    assert not _is_adversary_caption("Vance Vincent")
    assert not _is_adversary_caption("")
    assert not _is_adversary_caption(None)


def test_middle_initial_v_is_not_split_into_a_plaintiff_and_defendant():
    # case-insensitive matching turned this debtor into plaintiff "Mira",
    # defendant "Quill"
    assert _split_caption("Mira V. Quill") == (None, "Mira V. Quill")
    assert _split_caption("Alan V. Quill and Rene V. Quill") == (
        None, "Alan V. Quill and Rene V. Quill")
    # real captions still split
    assert _split_caption("Taylor v. Honeycutt") == ("Taylor", "Honeycutt")
    assert _split_caption("Batt vs. Cole") == ("Batt", "Cole")


def test_county_from_text_handles_empty_input():
    assert _county_from_text("", "NC") is None
    assert _county_from_text(None, "NC") is None  # type: ignore[arg-type]
    assert _county_from_text("Acme Widgets of Raleigh, Inc.", "") is None


# ---------------------------------------------------------------------------
# courtlistener_bankruptcy.fetch(): captions are not debtor petitions
# ---------------------------------------------------------------------------

def _docket(docket_no, case_name, **kw):
    return {
        "docket_number": docket_no,
        "case_name": case_name,
        "absolute_url": f"/docket/{docket_no}/",
        "date_filed": "2026-09-15",
        "chapter": "13",
        **kw,
    }


def _run_bankruptcy(per_court, monkeypatch):
    import foreclosure_scraper.scrapers.national.courtlistener_bankruptcy as M

    async def fake_fetch_court(c, court, token, deadline=None):
        return per_court.get(court, [])

    monkeypatch.setattr(M, "_fetch_court", fake_fetch_court)
    monkeypatch.setattr(M, "_load_token", lambda: "fake-token")
    return list(asyncio.run(CourtListenerBankruptcy().fetch()))


def test_bankruptcy_fetch_skips_adversary_captions_and_keeps_petitions(monkeypatch):
    rows = _run_bankruptcy({
        "ncwb": [
            _docket("26-50001", "Orla Q. Marshall"),                      # person petition
            _docket("26-50002", "Acme Widgets of Raleigh, Inc."),         # org petition
            _docket("26-03060", "Vale v. Acme Supply, LLC"),              # adversary
            _docket("26-03061", "Vale, Trustee v. Acme Funding LLC dba Quick Cash"),
            _docket("26-50003", "Mira V. Quill"),                         # middle initial
        ],
    }, monkeypatch)
    by_case = {li.case_number: li for li in rows}
    assert set(by_case) == {"26-50001", "26-50002", "26-50003"}, (
        "adversary-proceeding captions must not publish as debtor petitions")
    # the middle-initial debtor is kept whole, not split into plaintiff/defendant
    assert by_case["26-50003"].plaintiff is None
    assert by_case["26-50003"].defendant == "Mira V. Quill"


def test_bankruptcy_fetch_county_only_from_an_organization_name(monkeypatch):
    rows = _run_bankruptcy({
        "ncwb": [
            _docket("26-50001", "Orla Q. Marshall"),
            _docket("26-50002", "Acme Widgets of Raleigh, Inc."),
            _docket("26-50004", "Hollis Vanderson"),
            _docket("26-50005", "Prentice Jackson"),
        ],
        "scb": [
            _docket("26-60001", "Corbin Anderson"),
            _docket("26-60002", "Acme Widgets of Clinton LLC"),
        ],
    }, monkeypatch)
    county = {li.case_number: li.county for li in rows}
    assert county == {
        "26-50001": None,
        "26-50002": "Wake",
        "26-50004": None,
        "26-50005": None,
        "26-60001": None,
        "26-60002": "Laurens",
    }
    # the court's state is still authoritative
    assert {li.case_number: li.state for li in rows}["26-60002"] == "SC"


# ---------------------------------------------------------------------------
# the same flaw in courtlistener_adversary / courtlistener_civil
# ---------------------------------------------------------------------------

def test_adversary_scraper_person_debtor_gets_no_county(monkeypatch):
    async def fake_search(c, token, court, phrase):
        if court == "ncwb" and phrase == "relief from stay":
            return [
                {"caseName": "In re Prentice Jackson", "docketNumber": "26-40001",
                 "dateFiled": "2026-09-01", "chapter": "13",
                 "docket_absolute_url": "/docket/1/a/", "suitNature": "Relief from Stay"},
                {"caseName": "In re Acme Widgets of Raleigh, Inc.", "docketNumber": "26-40002",
                 "dateFiled": "2026-09-01", "chapter": "11",
                 "docket_absolute_url": "/docket/2/b/", "suitNature": "Relief from Stay"},
            ]
        return []

    monkeypatch.setattr(ADV, "_search", fake_search)
    monkeypatch.setattr(ADV, "_load_token", lambda: "fake-token")
    rows = {li.case_number: li for li in asyncio.run(ADV.CourtListenerAdversary().fetch())}
    assert rows["26-40001"].county is None
    assert rows["26-40002"].county == "Wake"


def test_civil_scraper_caption_gets_no_county(monkeypatch):
    # the real-property civil feed is "<Plaintiff> v. <Defendant>": a town in the
    # plaintiff ("Bank of Charlotte") or a borrower surname is not the property's county
    async def fake_fetch_court_civil(c, court, token, deadline=None):
        if court == "ncwd":
            return [
                CIV._normalize_search_hit({
                    "caseName": "Bank of Charlotte v. Prentice Jackson",
                    "docketNumber": "3:26-cv-00001", "dateFiled": "2026-09-01",
                    "suitNature": "220 Real Property: Foreclosure",
                    "docket_absolute_url": "/docket/3/c/"}, "ncwd"),
                CIV._normalize_search_hit({
                    "caseName": "Vale v. Raleigh Hotel Partners, LLC",
                    "docketNumber": "3:26-cv-00002", "dateFiled": "2026-09-01",
                    "suitNature": "220 Real Property: Foreclosure",
                    "docket_absolute_url": "/docket/4/d/"}, "ncwd"),
            ]
        return []

    monkeypatch.setattr(CIV, "_fetch_court_civil", fake_fetch_court_civil)
    monkeypatch.setattr(CIV, "_load_token", lambda: "fake-token")
    rows = list(asyncio.run(CIV.CourtListenerCivil().fetch()))
    assert len(rows) == 2
    assert all(li.county is None for li in rows)
    assert all(li.state == "NC" for li in rows)
