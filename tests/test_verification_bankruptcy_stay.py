"""bankruptcy_stay verifier, against REAL CourtListener responses captured live on 2026-10-06
(tests/fixtures/verification/courtlistener_bankruptcy_stay.json.gz: {url: body}). No network.

The repo is public, so the captured bodies keep everything the verifier reads (docket numbers
and ids, courts, chapters, filing and termination dates, every docket entry's date, number and
short description) but the debtor names are replaced by made-up names of the same shape (the
same middle-initial and joint-filer structure the real case had against the real board owner),
and entry texts that named a person read "Other". The board owners below are made up the same
way; each test says which real board shape it reproduces."""
from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import bankruptcy_stay as b

FIX = Path(__file__).parent / "fixtures" / "verification" / "courtlistener_bankruptcy_stay.json.gz"
TODAY = date(2026, 10, 6)
SERVED: dict = json.loads(gzip.decompress(FIX.read_bytes()))
FIXTURE_NAMES = ("Tolland", "Corwin", "Nelson", "Bell", "Lane", "Barlow", "Mercer", "Stanton",
                 "Cole", "Goodwin", "Beal", "Kemp", "Chapman")


@pytest.fixture(autouse=True)
def _hermetic_corroboration(monkeypatch, tmp_path):
    """v3: a stale answer on an unverified name match looks the person up in the repo's voter file
    and parcel roll. These tests must not read the real data/ (and must not depend on it)."""
    monkeypatch.setenv("VERIFY_NCVOTER_DIR", str(tmp_path / "no_voter_files"))
    monkeypatch.setattr(b, "_roll_owner", lambda row: None)


def served(*extra: tuple) -> ReplayFetcher:
    resp = dict(SERVED)
    resp.update(dict(extra))
    return ReplayFetcher(resp)


def run(row, fetcher=None, today=TODAY):
    f = fetcher or served()
    return asyncio.run(b.verify(row, f, today=today)), f


def _bk(court, case, dn, did, **kw):
    d = {"court": court, "case_name": case, "docket_number": dn,
         "absolute_url": f"/docket/{did}/x/", "match_strategy": "strict_subset"}
    d.update(kw)
    return d


def _row(owner, *, state="NC", county="Buncombe", lt="tax_lien", defendant=None, raw=None, **kw):
    r = {"state": state, "county": county, "listing_type": lt, "owner_name": owner,
         "defendant": owner if defendant is None else defendant, "street_address": "1 MAIN ST",
         "parcel_id": "1111-11-1111-00000", "raw": raw or {}}
    r.update(kw)
    return r


TOLLAND = _row("TOLLAND, BRIAN", raw={"bankruptcy": _bk(
    "ncwb", "Brian Carl Tolland", "26-10161", 73600081, date_filed="2026-07-10", chapter="13")})


def _cole(**raw_extra):
    raw = {"courtlistener": {"court": "ncwb", "chapter": "7"}}
    raw.update(raw_extra)
    return _row("Marissa Beth Cole", county="Polk", lt="bankruptcy", case_number="26-50391",
                source_url="https://www.courtlistener.com/docket/74829796/x/", raw=raw)


def _voter_file(tmp_path, monkeypatch, people, county_id="11"):
    """A made-up NC voter file (the real columns, tab-separated and quoted) for Buncombe (id 11):
    people = [(last, first, middle, street address)], all ACTIVE."""
    d = tmp_path / "voter"
    d.mkdir(exist_ok=True)
    head = ["county_id", "county_desc", "voter_reg_num", "last_name", "first_name", "middle_name",
            "voter_status_desc", "res_street_address", "res_city_desc"]
    lines = ["\t".join(f'"{h}"' for h in head)]
    for i, (last, first, mid, addr) in enumerate(people):
        cells = [county_id, "BUNCOMBE", f"{i:012d}", last, first, mid, "ACTIVE", f"{addr}   ", "ASHEVILLE"]
        lines.append("\t".join(f'"{c}"' for c in cells))
    (d / f"ncvoter{county_id}.txt").write_text("\n".join(lines) + "\n")
    monkeypatch.setenv("VERIFY_NCVOTER_DIR", str(d))


def _no_names(ev: dict) -> None:
    blob = json.dumps(ev).lower()
    for n in FIXTURE_NAMES:
        assert n.lower() not in blob, n
    assert "url" not in ev and "lookup" not in ev and "claimed" not in ev and "parties" not in ev


# ---------------------------------------------------------------------------
# contract and selection
# ---------------------------------------------------------------------------

def test_registered_with_the_exact_scorer_names():
    v = next(v for v in discover() if v.name == "bankruptcy_stay")
    assert (v.signal, v.version, v.ttl_days) == ("bankruptcy_stay", b.VERSION, 30.0)
    assert v.governs == ("bankruptcy", "bankruptcy_stay")
    # both are names the scorer and the lead-signal facets actually emit
    assert {"bankruptcy", "bankruptcy_stay"} <= set(ds.SIGNAL_CATEGORY)
    assert ds._LISTING_TYPE_SIGNAL["bankruptcy"]
    assert b.ROW_SUMMARY_EXCLUDE == ("owner_name",)


def test_applies_to_rows_that_carry_a_case_reference():
    assert b.applies(TOLLAND)
    stay_only = _row("DOE JANE", raw={"bankruptcy_stay": {"status": "stayed", "docket": "26-10161",
                                                          "court": "ncwb", "case": "Jane Q Doe"}})
    assert b.applies(stay_only)
    assert b.claim_of(stay_only)["from"] == "raw.bankruptcy_stay"
    assert b.applies(_cole()) and b.claim_of(_cole())["docket_id"] == 74829796
    # a listing-type filing with no property tie is not scored (F11) and not checked
    assert not b.applies(_row("DOE JANE", lt="bankruptcy", street_address=None, parcel_id=None,
                              source_url="https://www.courtlistener.com/docket/1/x/"))
    assert not b.applies(_row("DOE JANE", raw={"bankruptcy": {"case_name": "Jane Q Doe"}}))
    assert not b.applies(_row("DOE JANE"))


# ---------------------------------------------------------------------------
# verdicts on real responses
# ---------------------------------------------------------------------------

def test_stale_dismissed_chapter_13_the_board_scores_as_open(tmp_path, monkeypatch):
    """A Buncombe tax row's Chapter 13 match (owner LAST, FIRST with no middle). date_terminated
    is null on CourtListener; entry 25 'Dismissal' (2026-09-21) says the stay is gone. The match
    is "unverified" (no middle on the board), so since v3 it is stale only because the voter file
    holds exactly one registrant with the debtor's full name at the row's address."""
    _voter_file(tmp_path, monkeypatch, [("TOLLAND", "BRIAN", "CARL", "1 MAIN ST")])
    r, f = run(TOLLAND)
    assert r.verdict == "stale"
    assert r.evidence["identity_corroborated_by"] == "ncvoter"
    ev = r.evidence
    assert ev["event"] == {"kind": "dismissal", "date": "2026-09-21", "entry_number": 25}
    assert "date_terminated" not in ev                   # null at the source
    assert ev["owner_match"] == "unverified"             # no middle on the board: production's bar
    assert ev["decided_by"] == "dismissal+positional_match_unverified"
    assert (ev["court"], ev["court_state"], ev["docket_number"], ev["docket_id"], ev["chapter"]) == \
        ("ncwb", "NC", "26-10161", 73600081, "13")
    assert ev["date_filed"] == "2026-07-10" and ev["status"] == "closed"
    assert ev["match_field"] == "owner_name" and ev["claimed_from"] == "raw.bankruptcy"
    assert ev["debtor_middle_initials"] == ["C"] and "owner_middle_initial" not in ev
    assert "2026-09-02" in ev["relief_from_stay_dates"]
    assert r.signal == "bankruptcy_stay" and r.source == "courtlistener.com"
    assert r.verifier == "bankruptcy_stay" and r.verifier_version == b.VERSION
    _no_names(ev)


def test_stale_found_by_docket_number_when_the_row_has_only_the_stay(tmp_path, monkeypatch):
    _voter_file(tmp_path, monkeypatch, [("TOLLAND", "BRIAN", "CARL", "1 MAIN ST")])
    row = _row("TOLLAND, BRIAN", lt="foreclosure_sale", raw={"bankruptcy_stay": {
        "status": "stayed", "chapter": "13", "date_filed": "2026-07-10",
        "case": "Brian Carl Tolland", "docket": "26-10161", "court": "ncwb"}})
    r, f = run(row)
    assert r.verdict == "stale"
    assert f.asked[0] == b.SEARCH_BY_NUMBER.format(court="ncwb", dn="26-10161")
    assert r.evidence["claimed_from"] == "raw.bankruptcy_stay"


def test_stale_discharged_and_closed_long_open_case():
    """15-31086 (filed 2015, a board 'long_open' match): no date_terminated, but Discharge
    2022-05-25 and Final Decree/Case Closed 2022-09-15 in the entries. The owner here is built
    to match; the real board owner had the debtor's MIDDLE name as a first name (next test)."""
    row = _row("CORWIN, JEFFREY ALLEN", raw={"bankruptcy": _bk(
        "ncwb", "Jeffrey Allen Corwin and Sheri Dawn Fry Corwin", "15-31086", 7095900)})
    r, _ = run(row)
    assert r.verdict == "stale"
    assert r.evidence["event"] == {"kind": "closed", "date": "2022-09-15", "entry_number": 105}
    assert {"kind": "discharge", "date": "2022-05-25"} in r.evidence["terminal_events"]
    assert r.evidence["owner_match"] == "agrees"
    assert (r.evidence["owner_middle_initial"], r.evidence["debtor_middle_initials"]) == ("A", ["A"])


def test_refuted_owner_is_not_the_debtor_and_the_status_is_not_even_fetched():
    """Owner 'ALLEN, JEFFREY' was matched to 'Jeffrey Allen Corwin and ...': Allen is the
    debtor's middle name. A refuted record publishes how it was decided, nothing about the case.

    v4 (name patterns): this is the MAIDEN-NAME shape (the debtor's first name, the debtor's
    middle name as the owner's surname), so in a county the court covers it is no longer
    refuted (test_the_maiden_name_shape_in_a_covering_district_is_unconfirmed below). This test
    keeps the refuted record's shape on a Guilford row, a county of the Middle District: the
    W.D.N.C. court cannot cover it, the pattern does not count, and the verdict is what it was."""
    row = _row("ALLEN, JEFFREY", county="Guilford", raw={"bankruptcy": _bk(
        "ncwb", "Jeffrey Allen Corwin and Sheri Dawn Fry Corwin", "15-31086", 7095900)})
    r, f = run(row)
    assert r.verdict == "refuted"
    assert f.asked == [b.SEARCH_BY_ID.format(id=7095900)]
    assert r.evidence == {"decided_by": "no_positional_match", "owner_match": "none",
                          "match_field": "owner_name", "compared_fields": ["owner_name"],
                          "claimed_from": "raw.bankruptcy", "court": "ncwb", "court_state": "NC",
                          "debtor_count": 2}


@pytest.mark.parametrize("owner,court,case,dn,did,county", [
    # position-blind: the owner's FIRST name is the debtor's middle name. v4: the MIDDLE-AS-FIRST
    # shape, refuted only where the court cannot cover the property (a Guilford row, M.D.N.C.;
    # in a covering county it is unconfirmed: test_the_middle_as_first_shape_in_a_covering_...)
    ("NELSON, NEIL", "ncwb", "Gary Neil Nelson", "26-31203", 74733868, "Guilford"),
    # joint-filer phantom: first name of debtor 1 + surname of debtor 2; no such person in the case
    ("LANE, RONALD", "scb", "Ronald Curtis Bell and Sharon Marie Lane", "26-04126", 74756458, "Buncombe"),
])
def test_refuted_no_positional_match(owner, court, case, dn, did, county):
    r, _ = run(_row(owner, county=county, raw={"bankruptcy": _bk(court, case, dn, did)}))
    assert r.verdict == "refuted"
    assert r.evidence["decided_by"] == "no_positional_match"
    assert "docket_number" not in r.evidence
    _no_names(r.evidence)


def test_the_maiden_name_shape_in_a_covering_district_is_unconfirmed():
    """v3: refuted (no_positional_match). v4: the owner has the debtor's first name and the
    debtor's middle name as the surname, in a Buncombe row the W.D.N.C. court covers: unconfirmed,
    the claim keeps scoring. The same row in a county the court cannot cover stays refuted
    (test_refuted_owner_is_not_the_debtor_and_the_status_is_not_even_fetched)."""
    row = _row("ALLEN, JEFFREY", raw={"bankruptcy": _bk(
        "ncwb", "Jeffrey Allen Corwin and Sheri Dawn Fry Corwin", "15-31086", 7095900)})
    r, f = run(row)
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "name_pattern_possible_same_person"
    assert r.evidence["name_pattern"] == "maiden_name" and r.evidence["owner_match"] == "none"
    assert f.asked == [b.SEARCH_BY_ID.format(id=7095900)]
    _no_names(r.evidence)


def test_the_middle_as_first_shape_in_a_covering_district_is_unconfirmed():
    """v3: refuted. v4: owner 'NELSON, NEIL' has the debtor's surname and the debtor's middle
    name ('Gary Neil Nelson') as the first name, on a Buncombe row the W.D.N.C. court covers."""
    r, _ = run(_row("NELSON, NEIL", raw={"bankruptcy": _bk(
        "ncwb", "Gary Neil Nelson", "26-31203", 74733868)}))
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "name_pattern_possible_same_person"
    assert r.evidence["name_pattern"] == "middle_as_first"
    _no_names(r.evidence)


def test_refuted_middle_conflict_publishes_initials_only():
    """A HOT Pickens SC tax row: owner LAST FIRST R vs a debtor First H. Last."""
    row = _row("STANTON JAMES R", state="SC", county="Pickens", raw={"bankruptcy": _bk(
        "scb", "James Hollis Stanton", "26-04329", 74811874)})
    r, _ = run(row)
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "middle_conflict"
    assert (r.evidence["owner_middle_initial"], r.evidence["debtor_middle_initials"]) == ("R", ["H"])
    _no_names(r.evidence)


def test_refuted_case_not_found_after_three_lookups():
    url = b.DOCKET_URL.format(id=999999999)
    gone = httpx.HTTPStatusError("404", request=httpx.Request("GET", url),
                                 response=httpx.Response(404, request=httpx.Request("GET", url)))
    row = _row("SMITH, JOHN Q", raw={"bankruptcy": _bk("ncwb", "John Q Smith", "26-99999", 999999999)})
    r, f = run(row, served((url, gone)))
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "case_not_found"
    assert len(f.asked) == 3


def test_confirmed_open_case_matching_owner_and_middle():
    """A Lincoln NC row whose owner is 'Last, First Middle' of the first joint debtor; entries
    through 2026-10-05, nothing terminal."""
    row = _row("Beal, Nolan Edward", county="Lincoln", raw={"bankruptcy": _bk(
        "ncwb", "Nolan Edward Beal and Krista Brooke Beal", "26-40259", 74827840)})
    r, _ = run(row)
    assert r.verdict == "confirmed"
    ev = r.evidence
    assert ev["status"] == "open" and ev["last_activity"] == "2026-10-05"
    assert ev["decided_by"] == "open+positional_match_agrees"
    assert ev["docket_number"] == "26-40259" and "event" not in ev
    _no_names(ev)


def test_confirmed_scb_case_with_no_middle_on_the_board():
    row = _row("Wilma  Kemp", state="SC", county="Cherokee", raw={"bankruptcy": _bk(
        "scb", "Wilma Lane Kemp", "26-04110", 74753975)})
    r, _ = run(row)
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "unverified"


def test_listing_row_judged_against_the_owner_of_record_not_its_owner_name():
    """A Mecklenburg listing-type filing: owner_name 'KARA A GOODWIN' reads surname-first and
    would not match; the county record raw.gis.owner 'GOODWIN KARA  A' does."""
    row = _row("KARA  A GOODWIN", county="Mecklenburg", lt="bankruptcy",
               defendant="Dalton Gale Goodwin and Kara Ann Goodwin", case_number="26-31301",
               source_url="https://www.courtlistener.com/docket/74829114/x/",
               raw={"gis": {"owner": "GOODWIN KARA  A"}, "courtlistener": {"court": "ncwb"}})
    r, _ = run(row)
    assert r.verdict == "confirmed"
    assert r.evidence["match_field"] == "gis.owner" and r.evidence["owner_match"] == "agrees"
    assert r.evidence["claimed_from"] == "listing"


def test_refuted_listing_row_whose_snapped_parcel_belongs_to_someone_else():
    """A Polk listing-type filing geo-snapped onto another family's parcel:
    enrich_court_owner_verify recorded it, the parcel came back, owner_name is the debtor copy."""
    row = _cole(owner_mismatch={"defendant_surname": "cole", "snapped_owner": "PRUITT ANNA DILL"})
    r, f = run(row)
    assert r.verdict == "refuted"
    assert r.evidence["match_field"] == "owner_mismatch.snapped_owner"
    assert len(f.asked) == 1


# ---------------------------------------------------------------------------
# unconfirmed paths
# ---------------------------------------------------------------------------

def test_unconfirmed_listing_row_with_no_owner_of_record_is_never_fetched():
    r, f = run(_cole())          # owner_name is only the debtor's name copied over
    assert r.verdict == "unconfirmed"
    assert r.evidence == {"reason": "no_owner_of_record_on_board", "claimed_from": "listing"}
    assert f.asked == []


def test_unconfirmed_entity_owner_is_never_fetched():
    row = _row("BENNINGTON CREEK COMMUNITY ASSOCIATION INC", defendant="",
               raw={"bankruptcy": _bk("ncwb", "Jane Q Doe", "26-1", 1)})
    r, f = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_person_owner_on_board"
    assert f.asked == []


def test_unconfirmed_court_in_another_state():
    """A Greenville SC row matched to an nceb (NC) debtor: production's _COURT_STATE check
    rejects it, nothing says it is a different person."""
    row = _row("MERCER KAREN", state="SC", county="Greenville", raw={"bankruptcy": _bk(
        "nceb", "Karen Noble Mercer", "11-08880", 4956282)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "court_state_differs"
    assert r.evidence["court_state"] == "NC" and "docket_number" not in r.evidence


def test_unconfirmed_no_docket_entries():
    row = _row("BARLOW, JOHN", county="Wake", raw={"bankruptcy": _bk("nceb", "John Henry Barlow, III", "26-04305", 74832823)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed"
    assert (r.evidence["status"], r.evidence["reason"], r.evidence["entries_seen"]) == \
        ("unknown", "no_docket_entries", 0)


def test_unconfirmed_owner_name_and_defendant_disagree():
    """A Pickens SC row: owner LAST FIRST SCOTT conflicts, defendant First Edward Last agrees."""
    row = _row("CHAPMAN STEVEN SCOTT", state="SC", county="Pickens",
               defendant="Steven Edward Chapman", raw={"bankruptcy": _bk(
                   "scb", "Steven Edward Chapman and Kate Elise Chapman", "26-03536", 73707954)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "board_names_disagree"


def test_unconfirmed_debtor_is_the_defendant_but_not_the_owner_of_record():
    """The first live sweep's one doubtful 'confirmed' (v1): a distressed row whose defendant is
    the debtor while its owner_name names two other people of the same family."""
    row = _row("TOLLAND RODNEY A;TOLLAND FRANCINE M", defendant="Brian Carl Tolland",
               raw={"bankruptcy": _bk("ncwb", "Brian Carl Tolland", "26-10161", 73600081)})
    r, f = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "board_names_disagree"
    assert len(f.asked) == 1


def test_unconfirmed_all_caps_owner_that_only_matches_read_first_last():
    row = _row("KARA A GOODWIN", county="Mecklenburg", raw={"bankruptcy": _bk(
        "ncwb", "Dalton Gale Goodwin and Kara Ann Goodwin", "26-31301", 74829114)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "owner_name_order_ambiguous"


def test_unconfirmed_lookup_failure():
    row = _row("DOE, JANE", raw={"bankruptcy": {"case_name": "Jane Q Doe",
                                                "absolute_url": "/docket/123/x/"}})
    r, f = run(row, ReplayFetcher({}))
    assert r.verdict == "unconfirmed" and "LookupError" in r.evidence["reason"]
    assert len(f.asked) == 2       # the search, then /dockets/{id}/; neither is a 404
    assert "123" not in json.dumps(r.evidence)


def test_unconfirmed_entries_fetch_failure():
    resp = {k: v for k, v in SERVED.items() if "docket-entries" not in k}
    r, _ = run(TOLLAND, ReplayFetcher(resp))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "entries_fetch_failed"
    assert r.evidence["error"] == "LookupError"


# ---------------------------------------------------------------------------
# the rules (pure)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("Dismissal", "dismissal"),
    ("Order Dismissing Case", "dismissal"),
    ("Notice of Dismissal", "dismissal"),
    ("Order Granting Motion to Dismiss", "dismissal"),
    ("Discharge", "discharge"),
    ("Discharge of Debtor(s)", "discharge"),
    ("Final Decree/Case Closed", "closed"),
    ("Case Closed Without Discharge", "closed"),
    ("Order Reinstating Case", "reinstated"),
    ("Order Vacating Order of Dismissal", "reinstated"),
    ("Order Converting Case to Chapter 7", "converted"),
    ("Relief from Stay (fee)", "relief_from_stay"),
    ("Motion to Dismiss/Convert/Modify", None),
    ("Trustee Motion Dismiss/Convert/Modify", None),
    ("Notice and Motion to Dismiss or Convert at Confirmation Hearing if Documents Not Provided", None),
    ("Order Denying Motion to Dismiss", None),
    ("Motion for Discharge", None),
    ("Financial Management Course", None),
    ("Disposition of Hearing/Trial", None),
    # a real notice text from the capture: 'discharge' appears, nothing was discharged
    ("Notice of 341(a) Meeting of Creditors. 341(a) meeting to be held on 10/21/2026 at 01:00 PM "
     "at Zoom 341 Meeting. Last day to oppose discharge or dischargeability is 12/21/2026.", None),
    ("", None),
])
def test_classify_entry(text, kind):
    assert b.classify_entry(text) == kind


def _e(d, desc, n=None):
    return {"date_filed": d, "entry_number": n, "description": "",
            "recap_documents": [{"description": desc}]}


def test_status_rules():
    hit = {"date_terminated": None}
    assert b.case_status(hit, [_e("2026-09-01", "Plan")], TODAY)["status"] == "open"
    old = b.case_status(hit, [_e("2025-12-01", "Plan")], TODAY)
    assert (old["status"], old["reason"]) == ("unknown", "no_recent_docket_activity")
    assert b.case_status(hit, [], TODAY)["status"] == "unknown"
    # a reinstatement after the dismissal re-opens; a dismissal after it closes again
    st = b.case_status(hit, [_e("2026-09-01", "Dismissal"), _e("2026-09-20", "Order Reinstating Case")], TODAY)
    assert st["status"] == "open" and st["reinstated"]["date"] == "2026-09-20"
    st = b.case_status(hit, [_e("2026-08-01", "Order Reinstating Case"), _e("2026-09-01", "Dismissal")], TODAY)
    assert st["status"] == "closed"
    # dateTerminated decides on its own
    st = b.case_status({"date_terminated": "2026-07-13"}, [_e("2026-09-01", "Plan")], TODAY)
    assert st["status"] == "closed" and st["event"] == {"kind": "date_terminated", "date": "2026-07-13"}


def test_identity_feeds_every_co_owner_to_the_production_matcher():
    claim = {"from": "raw.bankruptcy"}
    row = _row("DOE JOHN PAUL;DOE JANE MARIE", defendant="Jane Marie Doe")
    j = b.judge_identity(row, claim, ["Jane Marie Doe"])
    assert j["verdict"] == "agrees"
    assert b.persons_of("DOE JOHN C JR, ROE JOHN, DOE WILLIAM M, POE MIRANDA") == \
        ["DOE JOHN C JR", "ROE JOHN", "DOE WILLIAM M", "POE MIRANDA"]
    assert b.persons_of("DOE, JOHN E JR") == ["DOE, JOHN E JR"]
    assert b.persons_of("SMITH HOLDINGS LLC") == []
    # a listing row's defendant is the debtor: never compared, and a copied owner_name neither
    lrow = _row("Jane Q Doe", lt="bankruptcy", defendant="Jane Q Doe")
    assert b.board_names(lrow, {"from": "listing"}) == []


# ---------------------------------------------------------------------------
# what is published (the ledger is pushed to a public repo)
# ---------------------------------------------------------------------------

def test_public_evidence_is_a_whitelist_and_idempotent():
    working = {"decided_by": "no_positional_match", "owner_match": "none", "court": "ncwb",
               "court_state": "NC", "debtor_count": 1, "debtor_case_name": "Jane Q Doe",
               "parties": ["Jane Q Doe"], "url": "https://x/docket/1/jane-q-doe/",
               "docket_number": "26-1", "claimed": {"from": "raw.bankruptcy", "case_name": "Jane Q Doe"},
               "match": {"field": "owner_name", "person": "DOE, JOHN",
                         "per_field": {"owner_name": {"name": "DOE, JOHN", "verdict": "none"}}}}
    pub = b.public_evidence("refuted", working)
    assert "Doe" not in json.dumps(pub) and "DOE" not in json.dumps(pub)
    assert "docket_number" not in pub
    assert b.public_evidence("refuted", pub) == pub


def test_migrate_ledger_rewrites_stored_entries_offline():
    r, _ = run(TOLLAND)
    full = {"court": "ncwb", "docket_number": "26-10161", "debtor_case_name": "Brian Carl Tolland",
            "url": "https://www.courtlistener.com/docket/73600081/brian-carl-tolland/",
            "event": {"kind": "dismissal", "date": "2026-09-21", "entry_number": 25,
                      "description": "Dismissal"}, "status": "closed",
            "match": {"field": "owner_name", "per_field": {"owner_name": {"name": "TOLLAND, BRIAN"}}}}
    led = SimpleNamespace(rows={"k": {"row": {"owner_name": "TOLLAND, BRIAN", "county": "Buncombe"},
                                      "latest": {"verdict": "stale", "evidence": full}}})
    assert b.migrate_ledger(led) == 1
    e = led.rows["k"]
    assert e["row"] == {"county": "Buncombe"}
    assert "Tolland" not in json.dumps(e) and "TOLLAND" not in json.dumps(e)
    assert e["latest"]["evidence"]["event"] == {"kind": "dismissal", "date": "2026-09-21", "entry_number": 25}
    assert b.migrate_ledger(led) == 0


# ---------------------------------------------------------------------------
# what scoring does with it
# ---------------------------------------------------------------------------

def _vrec(verdict):
    checked = datetime(2026, 10, 6, tzinfo=timezone.utc)
    return {"signal": "bankruptcy_stay", "verdict": verdict, "evidence": {}, "source": b.SOURCE,
            "checked_at": core.iso_z(checked), "verifier_version": b.VERSION,
            "verifier": "bankruptcy_stay",
            "expires_at": core.iso_z(checked + timedelta(days=b.TTL_DAYS)),
            "governs": list(b.GOVERNS)}


def _stayed_lead(verification=None):
    raw = {"bankruptcy": {"court": "ncwb", "case_name": "Brian Carl Tolland",
                          "docket_number": "26-10161", "date_filed": "2026-07-10", "chapter": "13"},
           "bankruptcy_stay": {"status": "stayed", "chapter": "13", "date_filed": "2026-07-10",
                               "resume_risk": "moderate", "case": "Brian Carl Tolland"}}
    if verification is not None:
        raw["verification"] = verification
    return Listing(source="nc_ecourts", source_url="https://x/y", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Buncombe", parcel_id="111111111100000",
                   street_address="1 MAIN ST", owner_name="TOLLAND, BRIAN", raw=raw)


def test_unverified_lead_carries_the_stay_and_the_bankruptcy_facets():
    li = _stayed_lead()
    assert ds._collect(li, None, TODAY).stay is not None
    assert {"bankruptcy", "bankruptcy_stay"} <= _facet_signals(li, TODAY)


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
def test_refuted_or_stale_lifts_the_stay_cap_and_both_signals(verdict):
    li = _stayed_lead([_vrec(verdict)])
    c = ds._collect(li, None, TODAY)
    assert c.stay is None
    assert "bankruptcy" not in {s[0] for s in c.signals}
    assert not ({"bankruptcy", "bankruptcy_stay"} & _facet_signals(li, TODAY))
    ds.score_board([li], previous_path=None)
    assert "stay" not in li.raw["distress_stack"]


@pytest.mark.parametrize("verdict", ["confirmed", "unconfirmed"])
def test_confirmed_or_unconfirmed_change_nothing(verdict):
    li = _stayed_lead([_vrec(verdict)])
    assert ds._collect(li, None, TODAY).stay is not None
    assert {"bankruptcy", "bankruptcy_stay"} <= _facet_signals(li, TODAY)
    ds.score_board([li], previous_path=None)
    assert li.raw["distress_stack"].get("stay")


# ---------------------------------------------------------------------------
# the ledger rule a VERSION bump depends on (verification/ledger.py _better)
# ---------------------------------------------------------------------------

def _answer(verdict, version, ts):
    return core.result(b.SIGNAL, verdict, {"reason": "x"} if verdict == "unconfirmed" else {},
                       source=b.SOURCE, version=version, verifier="bankruptcy_stay",
                       now=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc))


def test_a_version_bump_can_retract_a_verdict_through_the_disk_merge(tmp_path):
    """bankruptcy_stay v1 -> v2 (2026-10-06): record() let the v2 unconfirmed replace the v1
    confirmed, then _save() merged the file on disk back in and the v1 confirmed won."""
    from foreclosure_scraper.verification import ledger as L
    disk = L.Ledger.load(b.SIGNAL, tmp_path)
    disk.record(TOLLAND, _answer("confirmed", "v1", "2026-10-06T04:50:00"), ttl_days=30)
    disk.save()
    run_copy = L.Ledger.load(b.SIGNAL, tmp_path)
    e = run_copy.record(TOLLAND, _answer("unconfirmed", "v2", "2026-10-06T05:10:00"), ttl_days=30)
    assert e["latest"]["verifier_version"] == "v2"
    run_copy.merge_from(L.Ledger.load(b.SIGNAL, tmp_path))      # what _save() does
    (_, e), = run_copy.rows.items()
    assert (e["latest"]["verdict"], e["latest"]["verifier_version"]) == ("unconfirmed", "v2")
    # same version: a flaky unconfirmed still never erases a real verdict through the merge
    run2 = L.Ledger.load(b.SIGNAL, tmp_path)
    flaky = L.Ledger.load(b.SIGNAL, tmp_path)
    flaky.rows[next(iter(flaky.rows))]["latest"] = _answer("unconfirmed", "v1", "2026-10-06T06:00:00").to_dict()
    run2.merge_from(flaky)
    assert next(iter(run2.rows.values()))["latest"]["verdict"] == "confirmed"
