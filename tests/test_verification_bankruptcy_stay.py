"""bankruptcy_stay verifier, against REAL CourtListener responses captured live on 2026-10-06
(tests/fixtures/verification/courtlistener_bankruptcy_stay.json.gz: {url: body}). No network.

Board rows below are the real board values of the rows involved (owner_name, defendant, the
stored raw.bankruptcy / raw.bankruptcy_stay / raw.owner_mismatch), except where a test says it
builds a row to reach a path (e.g. the Conrad discharge under a matching owner)."""
from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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


def served(*extra: tuple) -> ReplayFetcher:
    resp = dict(SERVED)
    resp.update(dict(extra))
    return ReplayFetcher(resp)


def run(row, fetcher=None, today=TODAY):
    f = fetcher or served()
    return asyncio.run(b.verify(row, f, today=today)), f


def _bk(court, case, dn, did, slug="x", **kw):
    d = {"court": court, "case_name": case, "docket_number": dn,
         "absolute_url": f"/docket/{did}/{slug}/", "match_strategy": "strict_subset"}
    d.update(kw)
    return d


def _row(owner, *, state="NC", county="Buncombe", lt="tax_lien", defendant=None, raw=None, **kw):
    r = {"state": state, "county": county, "listing_type": lt, "owner_name": owner,
         "defendant": owner if defendant is None else defendant, "street_address": "1 MAIN ST",
         "raw": raw or {}}
    r.update(kw)
    return r


TALLANT = _row("TALLANT, BRYAN", street_address="539 DEAVERVIEW RD", parcel_id="9618-96-7879-00000",
               raw={"bankruptcy": _bk("ncwb", "Bryan Christopher Tallant", "26-10161", 73600081,
                                      date_filed="2026-07-10", chapter="13")})


def _canipe(**raw_extra):
    raw = {"courtlistener": {"court": "ncwb", "chapter": "7"}}
    raw.update(raw_extra)
    return _row("Miranda Beth Canipe", county="Polk", lt="bankruptcy", parcel_id="P48-21",
                street_address=None, case_number="26-50391",
                source_url="https://www.courtlistener.com/docket/74829796/miranda-beth-canipe/",
                raw=raw)


# ---------------------------------------------------------------------------
# contract and selection
# ---------------------------------------------------------------------------

def test_registered_with_the_exact_scorer_names():
    v = next(v for v in discover() if v.name == "bankruptcy_stay")
    assert (v.signal, v.version, v.ttl_days) == ("bankruptcy_stay", "v2", 30.0)
    assert v.governs == ("bankruptcy", "bankruptcy_stay")
    # both are names the scorer and the lead-signal facets actually emit
    assert {"bankruptcy", "bankruptcy_stay"} <= set(ds.SIGNAL_CATEGORY)
    assert ds._LISTING_TYPE_SIGNAL["bankruptcy"]


def test_applies_to_rows_that_carry_a_case_reference():
    assert b.applies(TALLANT)
    stay_only = _row("X Y", raw={"bankruptcy_stay": {"status": "stayed", "docket": "26-10161",
                                                     "court": "ncwb", "case": "A B"}})
    assert b.applies(stay_only)
    assert b.claim_of(stay_only)["from"] == "raw.bankruptcy_stay"
    assert b.applies(_canipe()) and b.claim_of(_canipe())["docket_id"] == 74829796
    # a listing-type filing with no property tie is not scored (F11) and not checked
    assert not b.applies(_row("A B", lt="bankruptcy", street_address=None,
                              source_url="https://www.courtlistener.com/docket/1/x/"))
    assert not b.applies(_row("A B", raw={"bankruptcy": {"case_name": "A B"}}))   # no docket
    assert not b.applies(_row("A B"))


# ---------------------------------------------------------------------------
# verdicts on real responses
# ---------------------------------------------------------------------------

def test_stale_dismissed_chapter_13_the_board_scores_as_open():
    """539 Deaverview Rd: the board's Chapter 13 match. date_terminated is null on CourtListener;
    entry 25 'Dismissal' (2026-09-21) is what says the stay is gone."""
    r, f = run(TALLANT)
    assert r.verdict == "stale"
    ev = r.evidence
    assert ev["event"] == {"kind": "dismissal", "date": "2026-09-21", "entry_number": 25,
                           "description": "Dismissal"}
    assert ev["date_terminated"] is None
    assert ev["owner_match"] == "unverified"          # TALLANT, BRYAN has no middle: production's bar
    assert ev["decided_by"] == "dismissal+positional_match_unverified"
    assert (ev["court"], ev["court_state"], ev["docket_number"], ev["chapter"]) == ("ncwb", "NC", "26-10161", "13")
    assert ev["date_filed"] == "2026-07-10"
    assert ev["debtor_case_name"] == "Bryan Christopher Tallant"
    assert ev["url"] == "https://www.courtlistener.com/docket/73600081/bryan-christopher-tallant/"
    assert ev["match"]["rule"].startswith("name_normalize.debtor_positional_match")
    assert any(e["date"] == "2026-09-02" for e in ev["relief_from_stay_entries"])
    assert r.signal == "bankruptcy_stay" and r.source == "courtlistener.com"
    assert r.verifier == "bankruptcy_stay" and r.verifier_version == b.VERSION


def test_stale_found_by_docket_number_when_the_row_has_only_the_stay():
    row = _row("TALLANT, BRYAN", lt="foreclosure_sale", raw={"bankruptcy_stay": {
        "status": "stayed", "chapter": "13", "date_filed": "2026-07-10",
        "case": "Bryan Christopher Tallant", "docket": "26-10161", "court": "ncwb"}})
    r, f = run(row)
    assert r.verdict == "stale"
    assert r.evidence["lookup"] == [b.SEARCH_BY_NUMBER.format(court="ncwb", dn="26-10161")]


def test_stale_discharged_and_closed_long_open_case():
    """15-31086 (Conrad, filed 2015, a board 'long_open' match): no date_terminated, but
    Discharge 2022-05-25 and Final Decree/Case Closed 2022-09-15 in the entries. The owner here
    is built to match; the real board owner is ALLEN, JEFFREY (next test)."""
    row = _row("CONRAD, JEFFREY ALLEN", raw={"bankruptcy": _bk(
        "ncwb", "Jeffrey Allen Conrad and Shari Don Freed Conrad", "15-31086", 7095900)})
    r, _ = run(row)
    assert r.verdict == "stale"
    assert r.evidence["event"]["kind"] == "closed" and r.evidence["event"]["date"] == "2022-09-15"
    kinds = {(e["kind"], e["date"]) for e in r.evidence["terminal_entries"]}
    assert ("discharge", "2022-05-25") in kinds
    assert r.evidence["owner_match"] == "agrees"


def test_refuted_owner_is_not_the_debtor_and_the_status_is_not_even_fetched():
    """12 White Walnut Dr: owner ALLEN, JEFFREY was matched to 'Jeffrey Allen Conrad and ...'
    ('Allen' is Conrad's middle name)."""
    row = _row("ALLEN, JEFFREY", raw={"bankruptcy": _bk(
        "ncwb", "Jeffrey Allen Conrad and Shari Don Freed Conrad", "15-31086", 7095900)})
    r, f = run(row)
    assert r.verdict == "refuted"
    assert r.evidence["decided_by"] == "no_positional_match"
    assert f.asked == [b.SEARCH_BY_ID.format(id=7095900)]


@pytest.mark.parametrize("owner,state,court,case,dn,did", [
    # position-blind: 'David' is Bryan Davis's middle name
    ("DAVIS, DAVID", "NC", "ncwb", "Bryan David Davis", "26-31203", 74733868),
    # joint-filer phantom: Robert (debtor 1) + Jones (debtor 2); no Robert Jones in the case
    ("JONES, ROBERT", "NC", "scb", "Robert Curtis Best and Shannon Marie Jones", "26-04126", 74756458),
])
def test_refuted_no_positional_match(owner, state, court, case, dn, did):
    r, _ = run(_row(owner, state=state, raw={"bankruptcy": _bk(court, case, dn, did)}))
    assert r.verdict == "refuted"
    assert r.evidence["decided_by"] == "no_positional_match"
    assert r.evidence["owner_match"] == "none"


def test_refuted_middle_conflict():
    """414 Rotterdam Rd (Pickens SC): STEWART JAMES R vs James Houston Stewart."""
    row = _row("STEWART JAMES R", state="SC", county="Pickens", raw={"bankruptcy": _bk(
        "scb", "James Houston Stewart", "26-04329", 74811874)})
    r, _ = run(row)
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "middle_conflict"


def test_refuted_case_not_found_after_three_lookups():
    url = b.DOCKET_URL.format(id=999999999)
    gone = httpx.HTTPStatusError("404", request=httpx.Request("GET", url),
                                 response=httpx.Response(404, request=httpx.Request("GET", url)))
    row = _row("SMITH, JOHN Q", raw={"bankruptcy": _bk("ncwb", "John Q Smith", "26-99999", 999999999)})
    r, f = run(row, served((url, gone)))
    assert r.verdict == "refuted" and r.evidence["decided_by"] == "case_not_found"
    assert len(f.asked) == 3


def test_confirmed_open_case_matching_owner_and_middle():
    """410 Lithia Inn Rd (Lincoln NC): 'Bean, Nathan Edward' vs 'Nathan Edward Bean and
    Kristen Brooke Bean', entries through 2026-10-05, nothing terminal."""
    row = _row("Bean, Nathan Edward", county="Lincoln", raw={"bankruptcy": _bk(
        "ncwb", "Nathan Edward Bean and Kristen Brooke Bean", "26-40259", 74827840)})
    r, _ = run(row)
    assert r.verdict == "confirmed"
    assert r.evidence["status"] == "open" and r.evidence["last_activity"] == "2026-10-05"
    assert r.evidence["decided_by"] == "open+positional_match_agrees"
    assert "event" not in r.evidence


def test_confirmed_scb_case_with_no_middle_on_the_board():
    row = _row("Wanda  King", state="SC", county="Cherokee", raw={"bankruptcy": _bk(
        "scb", "Wanda Lawless King", "26-04110", 74753975)})
    r, _ = run(row)
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "unverified"


def test_listing_row_judged_against_the_owner_of_record_not_its_copied_owner_name():
    """6333 Tunston Ln (Mecklenburg): owner_name 'KIMBERLY  A GOODALL' reads surname-first and
    would not match; the county record raw.gis.owner 'GOODALL KIMBERLY  A' does."""
    row = _row("KIMBERLY  A GOODALL", county="Mecklenburg", lt="bankruptcy",
               defendant="Dillon Gallas Goodall and Kimberly Ann Goodall", parcel_id="02951502",
               case_number="26-31301",
               source_url="https://www.courtlistener.com/docket/74829114/dillon-gallas-goodall-and-kimberly-ann-goodall/",
               raw={"gis": {"owner": "GOODALL KIMBERLY  A"}, "courtlistener": {"court": "ncwb"}})
    r, _ = run(row)
    assert r.verdict == "confirmed"
    assert r.evidence["match"]["field"] == "gis.owner" and r.evidence["owner_match"] == "agrees"


def test_refuted_listing_row_whose_snapped_parcel_belongs_to_someone_else():
    """P48-21 (Polk): the debtor's filing was geo-snapped onto BABS MIRANDA DILL's parcel;
    enrich_court_owner_verify recorded it, the parcel came back, owner_name is the debtor copy."""
    row = _canipe(owner_mismatch={"defendant_surname": "canipe", "snapped_owner": "BABS MIRANDA DILL"})
    r, f = run(row)
    assert r.verdict == "refuted"
    assert r.evidence["match"]["field"] == "owner_mismatch.snapped_owner"
    assert len(f.asked) == 1


# ---------------------------------------------------------------------------
# unconfirmed paths
# ---------------------------------------------------------------------------

def test_unconfirmed_listing_row_with_no_owner_of_record_is_never_fetched():
    r, f = run(_canipe())          # owner_name is only the debtor's name copied over
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "no_owner_of_record_on_board"
    assert f.asked == []


def test_unconfirmed_entity_owner_is_never_fetched():
    row = _row("BENNINGTON CREEK COMMUNITY ASSOCIATION INC", defendant="",
               raw={"bankruptcy": _bk("ncwb", "Jackie Saunders Price", "26-1", 1)})
    r, f = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_person_owner_on_board"
    assert f.asked == []


def test_unconfirmed_court_in_another_state():
    """1744 7th St (Greenville SC): MITCHELL KIMBERLY vs an nceb (NC) debtor; production's
    _COURT_STATE check rejects it, nothing says it is a different person."""
    row = _row("MITCHELL KIMBERLY", state="SC", county="Greenville", raw={"bankruptcy": _bk(
        "nceb", "Kimberly Nifong Mitchell", "11-08880", 4956282)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "court_state_differs"
    assert r.evidence["court_state"] == "NC"


def test_unconfirmed_no_docket_entries():
    row = _row("BARNES, JOHN", raw={"bankruptcy": _bk("nceb", "John Henry Barnes, III", "26-04305", 74832823)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed"
    assert (r.evidence["status"], r.evidence["reason"], r.evidence["entries_seen"]) == \
        ("unknown", "no_docket_entries", 0)


def test_unconfirmed_owner_name_and_defendant_disagree():
    """111 Pineview Dr (Pickens SC): owner CHASTAIN STEVEN SCOTT conflicts, defendant Steven
    Edward Chastain agrees."""
    row = _row("CHASTAIN STEVEN SCOTT", state="SC", county="Pickens",
               defendant="Steven Edward Chastain", raw={"bankruptcy": _bk(
                   "scb", "Steven Edward Chastain and Katelyn Elizabeth Chastain", "26-03536", 73707954)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "board_names_disagree"


def test_unconfirmed_debtor_is_the_defendant_but_not_the_owner_of_record():
    """The first live sweep's one doubtful 'confirmed' (v1): a distressed row whose defendant is
    the debtor while its owner_name names two other people."""
    row = _row("OVERCASH RODNEY A;OVERCASH FRANCINE M", defendant="Bryan Christopher Tallant",
               raw={"bankruptcy": _bk("ncwb", "Bryan Christopher Tallant", "26-10161", 73600081)})
    r, f = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "board_names_disagree"
    assert len(f.asked) == 1


def test_unconfirmed_all_caps_owner_that_only_matches_read_first_last():
    row = _row("KIMBERLY A GOODALL", county="Mecklenburg", raw={"bankruptcy": _bk(
        "ncwb", "Dillon Gallas Goodall and Kimberly Ann Goodall", "26-31301", 74829114)})
    r, _ = run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "owner_name_order_ambiguous"


def test_unconfirmed_lookup_failure():
    row = _row("DOE, JANE", raw={"bankruptcy": {"case_name": "Jane Q Doe",
                                                "absolute_url": "/docket/123/jane-q-doe/"}})
    r, f = run(row, ReplayFetcher({}))
    assert r.verdict == "unconfirmed" and "LookupError" in r.evidence["reason"]
    assert len(f.asked) == 2       # the search, then /dockets/{id}/; neither is a 404


def test_unconfirmed_entries_fetch_failure():
    resp = {k: v for k, v in SERVED.items() if "docket-entries" not in k}
    r, _ = run(TALLANT, ReplayFetcher(resp))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "entries_fetch_failed"


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
    row = _row("LAW BRANDON PETER;LAW BRITTANY LENORA", defendant="Brittany Lenora Law")
    j = b.judge_identity(row, claim, ["Brittany Lenora Law"])
    assert j["verdict"] == "agrees"
    assert b.persons_of("MCDOWELL JAMES C JR, BRUCE JOHN, MCDOWELL WILLIAM M, TYLER MIRANDA") == \
        ["MCDOWELL JAMES C JR", "BRUCE JOHN", "MCDOWELL WILLIAM M", "TYLER MIRANDA"]
    assert b.persons_of("BROWN, ROBERT E JR") == ["BROWN, ROBERT E JR"]
    assert b.persons_of("SMITH HOLDINGS LLC") == []
    # a listing row's defendant is the debtor: never compared, and a copied owner_name neither
    lrow = _row("Jane Q Doe", lt="bankruptcy", defendant="Jane Q Doe")
    assert b.board_names(lrow, {"from": "listing"}) == []


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
    raw = {"bankruptcy": {"court": "ncwb", "case_name": "Bryan Christopher Tallant",
                          "docket_number": "26-10161", "date_filed": "2026-07-10", "chapter": "13"},
           "bankruptcy_stay": {"status": "stayed", "chapter": "13", "date_filed": "2026-07-10",
                               "resume_risk": "moderate", "case": "Bryan Christopher Tallant"}}
    if verification is not None:
        raw["verification"] = verification
    return Listing(source="nc_ecourts", source_url="https://x/y", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Buncombe", parcel_id="961896787900000",
                   street_address="539 DEAVERVIEW RD", owner_name="TALLANT, BRYAN", raw=raw)


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
