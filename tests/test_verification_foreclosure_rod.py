"""The foreclosure_rod verifier (verification/verifiers/foreclosure_rod_buncombe.py): Buncombe NC
lis_pendens / foreclosure_sale rows against the Register of Deeds instrument chain of the board's
own parcel, and the Fetcher form sessions it fetches through.

What these pin:
  * the 84 live verdicts of 2026-10-06 (VERSION v2, docs/handoff/verification/foreclosure_rod.json)
    reproduce from the sweep's own responses (tests/fixtures/verification/
    foreclosure_rod_buncombe.json.gz: the county parcel layer's JSON and the ROD result pages,
    reduced to the grid and PSEUDONYMIZED, one name mapping throughout, middle initials,
    descriptions, book/pages, refs, dates and types kept; foreclosure_rod_cases.json: the rows),
    except the two v3 changed (V3_CHANGED: three agents re-checked all 103 stale verdicts live and
    found a trustee deed that closed ANOTHER borrower's loan, and one that described the lot next
    door);
  * v3's tie rule: a trustee deed ends THIS claim only when the claim's identity ties to it (the
    deed of trust the claim cites, a person the claim names on the deed / its deed of trust / the
    confirming initiation, or the board's exact address for a claim that names nobody), a weak
    street tie the county layer contradicts is unconfirmed, and the stale evidence records the
    tie, deed_predates_claim_days and an exact tie to the claim's own cited deed of trust;
  * every verdict path: confirmed (a recent substitute-trustee appointment; the row's own cited ROD
    instrument), stale (a trustee deed: borrower among its grantors, the parcel's vesting deed, the
    end of the confirming chain), refuted only on positive contrary evidence (cited instrument in
    another county; every deed of trust satisfied before a dated DOT-foreclosure claim; the claim
    person conveyed the parcel a year before a dated claim), and absence = unconfirmed;
  * identity: production's middle verdict, the vesting deed anchoring the owner's middle initial,
    other same-name people never counted, a description naming another lot never ties;
  * a challenge or block is `wall` and stops the run's later rows without a request;
  * no person name in any published evidence; rows without a property identity make no request;
  * scoring: a refuted/stale record drops lis_pendens / foreclosure_sale, the others change nothing.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import FormResponse, ReplayFetcher, form_key
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import foreclosure_rod_buncombe as fr

FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 6)

with gzip.open(FIX / "foreclosure_rod_buncombe.json.gz", "rt", encoding="utf-8") as _fh:
    _BUNDLE = json.load(_fh)
RESP = _BUNDLE["responses"]
PROBES = _BUNDLE["probes"]
CASES = json.loads((FIX / "foreclosure_rod_cases.json").read_text())["cases"]
BY_KEY = {c["key"]: c for c in CASES}


@pytest.fixture(autouse=True)
def _fresh_run_state():
    fr._RUNS.clear()
    yield
    fr._RUNS.clear()


def run(row, client=None):
    return asyncio.run(fr.verify(row, client if client is not None else ReplayFetcher(RESP), today=TODAY))


def case(key):
    return copy.deepcopy(BY_KEY[key]["row"])


# ---------------------------------------------------------------------------------------------
# the live sweep, reproduced
# ---------------------------------------------------------------------------------------------

#: what v3 answers on the two live cases it changed (the fixture holds what v2 answered):
#: 22SP000481 on 19 Violet Hill Cir (the notice's loan is not the loan the trustee deed foreclosed)
#: and 16 Saxon Hl (the trustee deed describes Lot 1 PB 151/6, which is 18 Saxon Hl)
V3_CHANGED = {"parcel:NC:buncombe:9658557367": ("unconfirmed", None, "tie_not_established"),
              "parcel:NC:buncombe:9685484456": ("unconfirmed", None, "deed_describes_adjacent_parcel")}


def test_every_live_verdict_reproduces_from_the_captured_responses():
    assert len(CASES) == 84
    got = Counter()
    for c in CASES:
        res = run(copy.deepcopy(c["row"]))
        want = V3_CHANGED.get(c["key"], (c["verdict"], c["decided_by"], c["reason"]))
        assert (res.verdict, res.evidence.get("decided_by"), res.evidence.get("reason")) == want, c["key"]
        got[res.verdict] += 1
    assert got == {"unconfirmed": 61, "confirmed": 18, "stale": 4, "refuted": 1}


def test_the_registry_finds_it_with_its_contract():
    v = next(v for v in discover() if v.signal == "foreclosure_rod")
    assert v.name == "foreclosure_rod_buncombe" and v.version == fr.VERSION == "v3"
    assert v.governs == ("lis_pendens", "foreclosure_sale")
    assert v.ttl_days == 14 and v.retry_days == 7 and not v.wall
    assert fr.ROW_SUMMARY_EXCLUDE == ("owner_name",)


def test_its_ledger_is_not_the_human_lanes():
    from foreclosure_scraper import verification_human_lane as hl
    assert fr.SIGNAL != "lis_pendens" and "lis_pendens" in hl.LEDGER_TTL_DAYS


# ---------------------------------------------------------------------------------------------
# applies / the claim
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("lt,state,county,ok", [
    ("lis_pendens", "NC", "Buncombe", True), ("foreclosure_sale", "NC", "buncombe", True),
    ("auction", "NC", "Buncombe", False), ("reo", "NC", "Buncombe", False),
    ("tax_sale", "NC", "Buncombe", False), ("foreclosure_sale", "NC", "Henderson", False),
    ("foreclosure_sale", "SC", "Buncombe", False)])
def test_applies(lt, state, county, ok):
    assert fr.applies({"listing_type": lt, "state": state, "county": county}) is ok


def test_claim_dates_and_kind():
    c = fr.claim_of({"source": "law_firms.hutchens", "listing_type": "foreclosure_sale",
                     "case_number": "22SP000481-100", "sale_date": "2026-09-22T00:00:00",
                     "first_seen": "2026-08-06T13:35:45"})
    assert (c["case_kind"], c["case_year"], c["earliest"]) == ("SP", 2022, "2022-01-01")
    assert c["dot_foreclosure"] is True
    n = fr.claim_of({"source": "counties.nod_discovery", "case_number": "6627/112",
                     "raw": {"nod": {"county": "Buncombe", "book": "6627", "page": "112",
                                     "doc_type": "SUBSTITUTE TRUSTEE",
                                     "recorded_date": "2026-09-03T00:00:00"}}})
    assert n["cited"] == {"county": "Buncombe", "book_page": "6627/112",
                          "doc_type": "SUBSTITUTE TRUSTEE", "recorded": "2026-09-03"}
    fc = fr.claim_of({"source": "national.foreclosure_dot_com", "case_number": "fc-66033266",
                      "first_seen": "2026-07-01T02:57:14"})
    assert fc["dot_foreclosure"] is False and "case_kind" not in fc and fc["earliest"] == "2026-07-01"


# ---------------------------------------------------------------------------------------------
# names and identity
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,sfc,want", [
    ("BURTON RICHARD B", True, [("BURTON", "RICHARD", "B")]),
    ("BURTON, RICHARD B.", True, [("BURTON", "RICHARD", "B")]),
    ("Rolland Ivan Rushing and Pamela Dee Rushing", True,
     [("RUSHING", "ROLLAND", "I"), ("RUSHING", "PAMELA", "D")]),
    ("DAVID EARL WISE", False, [("WISE", "DAVID", "E")]),           # a notice: FIRST ... LAST
    ("VAN DOOREN ELIZABETH ADRIENNE", True, [("VAN DOOREN", "ELIZABETH", "A")]),
    ("MASSIE(LE) DAVID A;FARMER(LE) JOYCE", True, [("MASSIE", "DAVID", "A"), ("FARMER", "JOYCE", "")]),
    ("FREDRICH, CHAD FREDRICH, TIA", True, [("FREDRICH", "CHAD", ""), ("FREDRICH", "TIA", "")]),
    ("SHOAF, MICHAEL EDWARD LAKEVIEW LOAN SERVICING, LLC/ BY AIF", True, [("SHOAF", "MICHAEL", "")]),
    ("KevinKerr", False, []), ("frenchbroadcontracting@gmail.com", False, []),
    ("JPMORGAN CHASE BANK NATIONAL ASSOCIATION", True, []),
    ("REGENIA SEBREN ANN EDWARDS JEFF FRIDAY HEIRS", True, [])])
def test_persons_in(value, sfc, want):
    assert fr.persons_in(value, surname_first_caps=sfc) == want


def test_middle_verdict_is_productions_rule():
    me = ("BURTON", "RICHARD", "B")
    assert fr.middle_verdict(me, "BURTON, RICHARD B.") == "agrees"
    assert fr.middle_verdict(me, "BURTON, RICHARD A") == "conflict"
    assert fr.middle_verdict(me, "BURTON, RICHARD") == "unverified"
    assert fr.middle_verdict(("BURTON", "RICHARD", ""), "BURTON, RICHARD A") == "unverified"
    assert fr.middle_verdict(("VAN DOOREN", "ELIZABETH", "A"), "VAN DOOREN, ELIZABETH B") == "conflict"


def test_owner_relation_tries_both_reading_orders_of_a_caps_name():
    owners = [("SPENCE", "ERIC", "A"), ("SPENCE", "JESSICA", "S")]
    assert fr.owner_relation(owners, ("HOPE", "JESSICA", "A"), "HOPE JESSICA ASHLEY BURNS") == "none"
    assert fr.owner_relation([("WISE", "DAVID", "E")], ("DAVID", "EARL", "W"), "DAVID EARL WISE") == "agrees"
    assert fr.owner_relation([], ("WISE", "DAVID", ""), "x") == "entity"
    assert fr.owner_relation(owners, None) is None


def test_foreclosure_com_defendant_counts_only_as_last_first():
    base = {"source": "national.foreclosure_dot_com", "owner_name": "ALLEN MICHAEL L"}
    assert [f for f, _, _ in fr.claim_persons({**base, "defendant": "RITTER, VIRGINIA"})] == \
        ["defendant", "owner_name"]
    assert [f for f, _, _ in fr.claim_persons({**base, "defendant": "Jnorton"})] == ["owner_name"]


def test_the_vesting_deed_anchors_the_owners_middle_initial():
    """A board name without a middle (a court caption) is anchored on the parcel's vesting deed:
    the same-name person with another middle initial is then someone else."""
    grid = fr.parse_grid(PROBES["dot_satisfied_no_later_loan"])
    me = fr.persons_in(json.loads(PROBES["dot_satisfied_no_later_loan_parcel"])["features"][0]["attributes"]["owner"])[0]
    bare = (me[0], me[1], "")
    assert fr._anchor_middle(grid, bare, "5305/1090") == me[2]
    keep, coll = fr.subject_docs(grid, bare, me[2])
    assert coll["same_name_middle_conflicts"] == 2           # an A and an E: other people
    keep_unanchored, _ = fr.subject_docs(grid, bare, "")
    assert len(keep) < len(keep_unanchored)


# ---------------------------------------------------------------------------------------------
# the grid, ties
# ---------------------------------------------------------------------------------------------

def test_parse_grid_reads_parties_bold_refs_and_desc_refs():
    g = fr.parse_grid(PROBES["dot_satisfied_no_later_loan"])
    assert g["count"] == 8 and len(g["docs"]) == 8 and not g["zero"]
    sat = next(d for d in g["docs"] if d["type"] == "DEED OF TRUST SATISFACTION")
    assert sat["refs"] == ["5305/1093"] and sat["matched_side"] == "grantor"
    html = ('<span>search returned <strong> 1</strong></span><table id="%s"><tr class="cottPagedGridViewRowStyle">'
            '<td>1</td><td>01/22/2003</td><td>CRP</td><td>DEED OF TRUST SATISFACTION</td>'
            '<td><div><table><tr><td><b>DOE, JANE</b></td></tr></table></div></td><td>X/ TR</td>'
            '<td>[D/T SAT ] DT 1634/489</td><td></td><td>3068 / 527</td><td></td>'
            '<td></td><td></td><td></td><td></td></tr></table>' % fr._GRID_ID)
    d = fr.parse_grid(html)["docs"][0]
    assert d["refs"] == ["1634/489"] and d["date"] == "2003-01-22" and d["matched"] == ["DOE, JANE"]
    z = fr.parse_grid(PROBES["zero_results"])
    assert z["zero"] and z["count"] == 0 and z["docs"] == []


@pytest.mark.parametrize("desc,attrs,want", [
    ("BILTMORE LAKE CANDLER Block:J Lot:909 GREENWELLS GLORY DR PH 1 PB 140/50",
     {"SubName": "BILTMORE LAKE", "SubLot": "909", "streetname": "GREENWELLS GLORY"}, "subdivision_lot"),
    ("AVERY PARK Lot:107C PH FOUR PB 130/55",
     {"SubName": "", "SubLot": "107C", "PlatBook": "0130", "PlatPage": "0055"}, "plat_lot"),
    ("FAIRVIEW TWP Lot:1 0.541 AC PB 151/6 SAXON HILL",
     {"SubLot": "", "streetname": "SAXON", "PlatBook": "0000", "PlatPage": "0000"}, "street"),
    ("WALTON ST LOT 15 BLOCK A PB 198/40", {"SubLot": "1 & 2", "streetname": "WALTON"}, None),
    ("LTS 467&468 SEC D PB 18/ 104 HI ALTA", {"SubLot": "468", "streetname": "HI ALTA"}, "street"),
    ("", {"streetname": "WALTON"}, None)])
def test_desc_tie(desc, attrs, want):
    assert fr.desc_tie(desc, attrs) == want


def test_ref_chain_inherits_the_deed_of_trusts_tie():
    g = fr.parse_grid(PROBES["dot_satisfied_no_later_loan"])
    a = json.loads(PROBES["dot_satisfied_no_later_loan_parcel"])["features"][0]["attributes"]
    t = fr.tie_docs(g["docs"], a)
    assert t["5305/1090"]["tie"] == "vesting_deed"
    assert t["5305/1093"] == {"tie": "subdivision_lot", "strength": "strong"}
    assert t["6091/1900"]["tie"] == "ref_chain" and t["6091/1900"]["strength"] == "strong"
    assert not any(bp in t for bp in ("5802/1615", "4049/892", "1993/33"))   # other people's lots


# ---------------------------------------------------------------------------------------------
# verdict paths, from the live cases
# ---------------------------------------------------------------------------------------------

def _ev(key):
    return run(case(key)).evidence


def test_confirmed_a_recent_substitute_trustee_for_this_owner_and_parcel():
    res = run(case("parcel:NC:buncombe:9770205617"))
    assert res.verdict == "confirmed" and res.evidence["decided_by"] == "initiation_on_record"
    li = res.evidence["latest_initiation"]
    assert li["type"] == "SUBSTITUTE TRUSTEE" and li["tie"] == "ref_chain" and li["refs"]


def test_confirmed_an_old_appointment_needs_a_current_claim():
    """22SP000481: a 2021 appointment, more than two years old, with a sale dated this year."""
    row = case("parcel:NC:buncombe:9701412633")
    assert run(row).verdict == "confirmed"
    row.pop("sale_date")
    res = run(row)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "initiation_old_no_outcome_at_rod"


def test_confirmed_the_rows_own_cited_instrument():
    key = next(c["key"] for c in CASES if c["row"].get("source") == "counties.nod_discovery"
               and c["verdict"] == "confirmed")
    ev = _ev(key)
    assert ev["decided_by"] == "cited_instrument_on_record"
    assert ev["cited_found"]["book_page"] == ev["cited_instrument"]["book_page"]


def test_stale_the_parcels_vesting_deed_is_a_trustee_deed():
    res = run(case("parcel:NC:buncombe:0634048334"))
    assert res.verdict == "stale" and res.evidence["decided_by"] == "trustee_deed_recorded"
    d = res.evidence["deciding"][0]
    assert d["tie"] == "vesting_deed" and d["type"] == "TRUSTEE DEED" and d["refs"]
    assert res.evidence["searches"][0]["role"] == "owner_entity"


def test_unconfirmed_the_trustee_deed_describes_the_lot_next_door():
    """16 Saxon Hl (the live case): trustee deed 6617/1720 (2026-08-03) and its deed of trust
    describe Lot 1 PB 151/6, which is 18 Saxon Hl, not 16: only a street tie holds the deed to the
    board's parcel and the county layer's parcel for the property is not the one the deed describes
    (county_layer_agrees False, tie weak). The foreclosure the listing describes did complete, but
    on the neighbouring parcel: v2 said stale; v3 refuses to say it of THIS one."""
    res = run(case("parcel:NC:buncombe:9685484456"))
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "deed_describes_adjacent_parcel"
    assert ev["county_layer_agrees"] is False and ev["ends_initiation"] is True
    d = ev["deciding"][0]
    assert d["type"] == "TRUSTEE DEED" and d["book_page"] == "6617/1720" and d["tie_strength"] == "weak"
    assert "decided_by" not in ev and "human_lane" in ev           # unconfirmed points at the human lane


def test_stale_judged_against_the_borrowers_acquisition_not_the_later_buyers():
    """1410 Double Knob Loop: trustee deed to the lender 2026-04-27, the lender's resale 2026-09-08."""
    ev = _ev("parcel:NC:buncombe:9623271978")
    assert ev["decided_by"] == "trustee_deed_recorded" and ev["county_layer_agrees"] is True
    assert ev["claim_person_among_grantors"] in ("agrees", "unverified")
    assert ev["claim_tie"] == "claim_person_on_deed"


def test_unconfirmed_a_trustee_deed_for_another_borrowers_loan_never_ends_the_claim():
    """The notice 22SP000481 (sale 2026-08-18) names borrowers who appear nowhere on 19 Violet Hill
    Cir's chain; the parcel's vesting deed is trustee deed 6622/1036 (2026-08-20, to an agency),
    which forecloses deed of trust 6174/1389 made by a DIFFERENT borrower. The real property is
    16 Overlook Dr, where the notice's own loan (4323/52) is open and no trustee deed is recorded.
    v2 called the Violet Hill row stale (the deed IS the parcel's vesting deed, a strong tie); the
    deed ties to the PARCEL, not to this CLAIM: unconfirmed, tie_not_established."""
    res = run(case("parcel:NC:buncombe:9658557367"))
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "tie_not_established"
    assert ev["claim_person_among_grantors"] == "none" and "claim_tie" not in ev
    d = ev["deciding"][0]
    assert d["type"] == "TRUSTEE DEED" and d["book_page"] == "6622/1036" and d["refs"] == ["6174/1389"]
    assert d["tie"] == "vesting_deed"                       # tied to the parcel, which is not the question
    assert ev["parcel"]["board_address_agrees"] is None     # the board's "address" is notice text
    # the same notice on its real parcel is still confirmed (its own loan, a 2021 appointment)
    assert run(case("parcel:NC:buncombe:9701412633")).verdict == "confirmed"


def test_stale_evidence_records_that_the_deed_predates_the_listing():
    """67 Earwood Ridge Rd and 630 Shumont Rd: the trustee deed (to the lender, REO) was recorded
    329 and 18 days BEFORE the listing's first_seen: the listing is a resale of an already
    foreclosed home. Stale stays right in effect (the claim is not live); the evidence says so."""
    for key, days in (("parcel:NC:buncombe:9677320315", 329), ("parcel:NC:buncombe:0634048334", 18)):
        res = run(case(key))
        ev = res.evidence
        assert res.verdict == "stale" and ev["decided_by"] == "trustee_deed_recorded", key
        assert ev["deed_predates_claim_days"] == days, key
        assert ev["claim_tie"] == "property_address" and ev["parcel"]["board_address_agrees"] is True
        assert "claim_person_among_grantors" not in ev       # the claim names nobody
    # a deed recorded AFTER the listing was first seen carries no such field
    ev = _ev("parcel:NC:buncombe:9688469881")                # 111 Telkaif Way: deed 22 days later
    assert ev["decided_by"] == "trustee_deed_recorded" and "deed_predates_claim_days" not in ev
    assert _ev("parcel:NC:buncombe:9623271978")["deed_predates_claim_days"] == 17


def test_refuted_the_cited_instrument_is_another_countys():
    res = run(case("parcel:NC:buncombe:9606599511"))
    assert res.verdict == "refuted" and res.evidence["decided_by"] == "cited_instrument_other_county"
    assert res.evidence["cited_instrument"]["county"] == "Cleveland"


def test_unconfirmed_when_rod_shows_nothing_and_points_to_the_human_lane():
    c = next(c for c in CASES if c["reason"] == "no_foreclosure_instrument_at_rod")
    ev = run(copy.deepcopy(c["row"])).evidence
    assert "lis_pendens" in ev["human_lane"] and "verify_lead_human_assisted" in ev["human_lane"]
    assert {c["reason"] for c in CASES if c["verdict"] == "unconfirmed"} >= {
        "no_foreclosure_instrument_at_rod", "parcel_chain_not_found_at_rod", "no_property_identity",
        "no_person_to_search"}


def test_no_property_identity_makes_no_request():
    c = next(c for c in CASES if c["reason"] == "no_property_identity" and not c["row"].get("raw"))
    client = ReplayFetcher({})
    res = run(copy.deepcopy(c["row"]), client)
    assert res.verdict == "unconfirmed" and client.asked == []


def test_a_fetch_failure_is_unconfirmed():
    res = run(case("parcel:NC:buncombe:9770205617"), ReplayFetcher({}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "county_layer_failed"


# ---------------------------------------------------------------------------------------------
# the two refutations no live row reached, on real pages
# ---------------------------------------------------------------------------------------------

def _probe_parcel():
    return json.loads(PROBES["dot_satisfied_no_later_loan_parcel"])["features"][0]["attributes"]


def _owner_search(grid=None):
    a = _probe_parcel()
    g = grid or fr.parse_grid(PROBES["dot_satisfied_no_later_loan"])
    return {"role": "owner", "subject": fr.persons_in(a["owner"])[0], "grid": g,
            "complete": g["count"] == len(g["docs"]), "narrowed": False}


DOT_CLAIM = {"listing_type": "foreclosure_sale", "source": "law_firms.hutchens", "case_kind": "SP",
             "case_year": 2026, "dates": {"case_year": "2026-01-01"}, "earliest": "2026-01-01",
             "dot_foreclosure": True}


def test_refuted_every_deed_of_trust_satisfied_before_a_dated_dot_claim():
    v, ev = fr.decide(DOT_CLAIM, _probe_parcel(), [_owner_search()], today=TODAY, owner_rel="agrees")
    assert v == "refuted" and ev["decided_by"] == "no_open_deed_of_trust"
    assert ev["deeds_of_trust_since_vesting"] == 1 and ev["last_satisfaction"] == "2021-07-12"


@pytest.mark.parametrize("change", ["not_a_dot_claim", "undated_claim", "satisfied_after_claim",
                                    "loan_still_open", "incomplete_search", "owner_differs"])
def test_no_refutation_without_every_condition(change):
    claim, rel = copy.deepcopy(DOT_CLAIM), "agrees"
    s = _owner_search()
    if change == "not_a_dot_claim":
        claim["dot_foreclosure"] = False
    elif change == "undated_claim":
        claim["dates"] = {"first_seen": "2026-01-01"}
    elif change == "satisfied_after_claim":
        claim.update(earliest="2021-01-01", dates={"case_year": "2021-01-01"})
    elif change == "loan_still_open":
        s["grid"]["docs"] = [d for d in s["grid"]["docs"] if d["type"] != "DEED OF TRUST SATISFACTION"]
        s["grid"]["count"] = len(s["grid"]["docs"])
    elif change == "incomplete_search":
        s["complete"] = False
    elif change == "owner_differs":
        rel = "none"
    v, _ = fr.decide(claim, _probe_parcel(), [s], today=TODAY, owner_rel=rel)
    assert v == "unconfirmed"


def test_refuted_the_claim_person_conveyed_the_parcel_a_year_before_the_claim():
    """The same real page: the OTHER same-name person (middle A) conveyed lot 28A on 2019-08-21;
    a dated 2026 claim naming him on that lot, with the current owner's search empty."""
    lot28a = {"pin": "0000000000", "pinext": "00000", "owner": "OWNER NEW", "SubLot": "28A",
              "PlatBook": "0097", "PlatPage": "0110", "streetname": "BEAR TRACK",
              "DeedBook": "5802", "DeedPage": "1615", "DeedDate": "20190821"}
    who = fr.rod_name_parts(PROBES["other_person_a"])
    g = fr.parse_grid(PROBES["dot_satisfied_no_later_loan"])
    zero = fr.parse_grid(PROBES["zero_results"])
    searches = [{"role": "owner", "subject": ("OWNER", "NEW", ""), "grid": zero, "complete": True, "narrowed": False},
                {"role": "claim_person", "subject": who, "grid": g, "complete": True, "narrowed": False}]
    claim = {**DOT_CLAIM, "dot_foreclosure": False}
    v, ev = fr.decide(claim, lot28a, searches, today=TODAY, owner_rel="none")
    assert v == "refuted" and ev["decided_by"] == "conveyed_before_claim"
    assert ev["deciding"][0]["book_page"] == "5802/1615"
    # within a year of the claim it is not
    late = {**claim, "earliest": "2020-03-01", "dates": {"case_year": "2020-03-01"}}
    assert fr.decide(late, lot28a, searches, today=TODAY, owner_rel="none")[0] == "unconfirmed"
    # and never on an undated claim (first_seen is when the board noticed, not when it was filed)
    undated = {**claim, "dates": {"first_seen": "2026-01-01"}}
    assert fr.decide(undated, lot28a, searches, today=TODAY, owner_rel="none")[0] == "unconfirmed"


# ---------------------------------------------------------------------------------------------
# v3: what ties a trustee deed to THIS claim, on the live shapes (pseudonymized, built by hand)
# ---------------------------------------------------------------------------------------------

def _d(n, date_, typ, bp, *, refs=(), grantors=(), grantees=(), matched=(), side="grantor", desc=""):
    return {"n": n, "date": date_, "type": typ, "bp": bp, "refs": list(refs), "grantors": list(grantors),
            "grantees": list(grantees), "matched": list(matched), "matched_side": side, "desc": desc}


def _grid(*docs):
    return {"count": len(docs), "docs": list(docs), "zero": False}


#: 19 Violet Hill Cir's shape: the county's vesting deed IS the trustee deed (to an agency); the
#: borrower on it is not the notice's
_TD_PARCEL = {"pin": "9658557367", "pinext": "00000", "owner": "EXAMPLE AGENCY", "DeedBook": "6622",
              "DeedPage": "1036", "DeedDate": "20260820", "SubName": "", "SubLot": "",
              "PlatBook": "0094", "PlatPage": "0126", "streetname": "VIOLET HILL"}
_NOTICE = {"listing_type": "foreclosure_sale", "source": "public_notices.nc_notices_counties",
           "case_kind": "SP", "case_year": 2022, "earliest": "2022-01-01", "dot_foreclosure": True,
           "dates": {"case_year": "2022-01-01", "first_seen": "2026-08-06", "sale_date": "2026-08-18"}}


def _td_search(grantors=("ROE, JANE",)):
    td = _d(1, "2026-08-20", "TRUSTEE DEED", "6622/1036", refs=["6174/1389"],
            grantors=[*grantors, "EXAMPLE TRUSTEE SERVICES, INC./ TR"],
            grantees=["EXAMPLE AGENCY", "DOE MARY"], matched=["EXAMPLE AGENCY"], side="grantee",
            desc="ASHEVILLE TRACT B PB 94/126 VIOLET HILL CIR")
    return [{"role": "owner_entity", "subject": ("EXAMPLE AGENCY", "", ""), "grid": _grid(td),
             "complete": True, "narrowed": False, "window": ["2026-08-13", "2026-08-27"]}]


def _decide_td(claim=None, **kw):
    kw.setdefault("owner_rel", "entity")
    return fr.decide(claim or _NOTICE, _TD_PARCEL, _td_search(kw.pop("grantors", ("ROE, JANE",))),
                     today=TODAY, **kw)


def test_the_tie_a_person_the_claim_names_must_be_on_the_deed():
    v, ev = _decide_td(claim_people=[("DOE", "JOHN", "")])                # the notice's borrower: not on it
    assert v == "unconfirmed" and ev["reason"] == "tie_not_established"
    assert ev["claim_person_among_grantors"] == "none" and ev["deciding"][0]["book_page"] == "6622/1036"
    v, ev = _decide_td(claim_people=[("ROE", "JANE", "")])                # on it (no middle either side)
    assert v == "stale" and ev["claim_tie"] == "claim_person_on_deed"
    assert ev["claim_person_among_grantors"] == "unverified" and ev["county_layer_agrees"] is True
    v, ev = _decide_td(claim_people=[("DOE", "JOHN", ""), ("ROE", "JANE", "Q")], grantors=("ROE, JANE Q",))
    assert v == "stale" and ev["claim_person_among_grantors"] == "agrees"   # any person the claim names
    # the same name with another middle initial is another person
    v, ev = _decide_td(claim_people=[("ROE", "JANE", "Q")], grantors=("ROE, JANE R",))
    assert v == "unconfirmed" and ev["claim_person_among_grantors"] == "conflict"


def test_the_tie_the_deed_of_trust_the_claim_cites_is_the_one_the_deed_forecloses():
    cited = {**_NOTICE, "cited_dot": ["6174/1389"]}
    v, ev = _decide_td(cited, claim_people=[("DOE", "JOHN", "")])        # whoever the notice names
    assert v == "stale" and ev["claim_tie"] == "claim_cited_dot"
    assert ev["deciding"][0]["tie"] == "claim_cited_dot" and ev["deciding"][0]["tie_strength"] == "exact"
    other = {**_NOTICE, "cited_dot": ["4323/52"]}                          # another loan
    v, ev = _decide_td(other, claim_people=[("DOE", "JOHN", "")])
    assert v == "unconfirmed" and ev["reason"] == "tie_not_established"


def test_the_tie_a_claim_that_names_nobody_needs_the_boards_exact_address():
    reo = {**_NOTICE, "source": "national.zillow_foreclosures", "dot_foreclosure": False,
           "dates": {"first_seen": "2026-09-30"}, "earliest": "2026-09-30"}
    v, ev = _decide_td(reo, claim_people=[], address_agrees=True)
    assert v == "stale" and ev["claim_tie"] == "property_address" and ev["deed_predates_claim_days"] == 41
    for agrees in (None, False):                  # a notice-text fragment, or another house on the street
        v, ev = _decide_td(reo, claim_people=[], address_agrees=agrees)
        assert v == "unconfirmed" and ev["reason"] == "tie_not_established"
        assert "claim_person_among_grantors" not in ev


def test_the_tie_the_deed_of_trust_in_the_results_made_by_a_claim_person():
    """A loan made by the claim's person that the deed forecloses, found in the person's own
    results, ties the claim even when the deed's party list names someone else."""
    me = ("ROE", "JANE", "")
    dot = _d(2, "2019-03-01", "DEED OF TRUST", "6174/1389", grantors=["ROE, JANE"], grantees=["EXAMPLE BANK"],
             matched=["ROE, JANE"], desc="ASHEVILLE TRACT B PB 94/126 VIOLET HILL CIR")
    searches = _td_search(grantors=("DOE, JOHN",)) + [
        {"role": "claim_person", "subject": me, "grid": _grid(dot), "complete": True, "narrowed": False}]
    v, ev = fr.decide(_NOTICE, _TD_PARCEL, searches, today=TODAY, owner_rel="entity", claim_people=[me])
    assert v == "stale" and ev["claim_tie"] == "claim_person_on_deed_of_trust"


def test_the_tie_the_confirming_initiation_of_the_loan_the_deed_forecloses():
    """The claim's person is on the substitute-trustee appointment (the confirming initiation) of
    the very loan the trustee deed forecloses, though the deed's party list carries only the
    lender: the claim's own foreclosure ended (stale). The same deed with no such initiation on the
    claim person is another loan's."""
    me = ("ROE", "JANE", "")
    init = _d(2, "2026-05-01", "SUBSTITUTE TRUSTEE", "6600/10", refs=["6174/1389"], grantors=["ROE, JANE"],
              grantees=["EXAMPLE TRUSTEE SERVICES, INC./ TR"], matched=["ROE, JANE"],
              desc="ASHEVILLE TRACT B PB 94/126 VIOLET HILL CIR")
    own = {"role": "claim_person", "subject": me, "grid": _grid(init), "complete": True, "narrowed": False}
    v, ev = fr.decide(_NOTICE, _TD_PARCEL, _td_search(("DOE, JOHN",)) + [own], today=TODAY,
                      owner_rel="entity", claim_people=[me])
    assert v == "stale" and ev["claim_tie"] == "claim_person_on_initiation" and ev["ends_initiation"] is True
    init["refs"] = ["4323/52"]                       # another loan's appointment: nothing ties the deed
    v, ev = fr.decide(_NOTICE, _TD_PARCEL, _td_search(("DOE, JOHN",)) + [own], today=TODAY,
                      owner_rel="entity", claim_people=[me])
    # not stale; the claim's own appointment is then judged as before (the parcel changed hands
    # after it and nothing satisfied its loan)
    assert v == "unconfirmed" and "claim_tie" not in ev
    assert ev["reason"] == "conveyed_after_initiation_no_satisfaction_yet"


def test_cited_dots_come_from_the_claim_itself_never_from_the_property_history():
    hutchens = {"source": "law_firms.hutchens", "listing_type": "foreclosure_sale",
                "description": "Hutchens trustee sale, court case 21SP000271-100, firm file 21-1234, "
                               "deed of trust book/page 2418/229",
                "raw": {"rod_docs": [{"doc_type": "DEED OF TRUST", "book": "2418", "page": "229",
                                     "county": "Buncombe", "state": "NC", "source": "law_firms.hutchens"}]}}
    assert fr.cited_dots(hutchens) == ["2418/229"]
    assert fr.claim_of({**hutchens, "case_number": "21SP000271-100"})["cited_dot"] == ["2418/229"]
    # a ROD enricher's name-index finds are the property's history, not the claim
    history = {"raw": {"rod_docs": [{"doc_type": "DEED OF TRUST", "book": "1111", "page": "22",
                                     "source": "aumentum_rod"}]}}
    assert fr.cited_dots(history) == [] and "cited_dot" not in fr.claim_of(history)
    assert fr.cited_dots({"description": "deed of trust book 2418"}) == []
    assert fr.cited_dots({"description": "x", "raw": {"rod_docs": "junk"}}) == []


def test_all_claim_people_reads_every_name_the_claim_carries():
    row = {"source": "public_notices.nc_notices_counties", "defendant": "Jane Q. Roe and John Roe",
           "owner_name": "ROE JANE Q;DOE MARY"}
    got = fr.all_claim_people(row)
    assert ("ROE", "JANE", "Q") in got and ("ROE", "JOHN", "") in got and ("DOE", "MARY", "") in got
    assert len(got) == 3                                         # ROE JANE counted once
    fc = {"source": "national.foreclosure_dot_com", "defendant": "KevinKerr", "owner_name": "DOE, MARY"}
    assert fr.all_claim_people(fc) == [("DOE", "MARY", "")]


def test_stale_the_loan_the_claim_cites_was_paid_off_is_an_exact_tie():
    """155 Old County Home Rd (the live case, pseudonymized): the Hutchens notice (21SP000271, sale
    2026-09-22) cites deed of trust 2418/229. Deed of trust satisfaction 6623/388 (2026-08-21) refers
    to exactly that loan, after a new loan (2026-07-28): a refinance payoff. The verdict is stale
    either way; the ledger recorded the tie as 'weak' (a ref chain from a street-described deed of
    trust), but it is the claim's own cited loan: exact."""
    me = ("ROE", "JANE", "Q")
    docs = [
        _d(1, "2003-04-10", "DEED OF TRUST", "2418/229", grantors=["ROE, JANE Q"], grantees=["EXAMPLE BANK"],
           matched=["ROE, JANE Q"], desc="OLD COUNTY HOME RD LOT 4"),
        _d(2, "2021-06-25", "SUBSTITUTE TRUSTEE", "6084/1652", refs=["2418/229"],
           grantors=["ROE, JANE Q", "EXAMPLE BANK"], grantees=["EXAMPLE TRUSTEE SERVICES, INC./ TR"],
           matched=["ROE, JANE Q"]),
        _d(3, "2026-07-28", "DEED", "6615/1759", grantors=["ROE, JANE Q"], grantees=["ROE, JANE Q"],
           matched=["ROE, JANE Q"], side="grantorgrantee", desc="OLD COUNTY HOME RD"),
        _d(4, "2026-07-28", "DEED OF TRUST", "6615/1762", grantors=["ROE, JANE Q"], grantees=["OTHER BANK"],
           matched=["ROE, JANE Q"], desc="OLD COUNTY HOME RD"),
        _d(5, "2026-08-21", "DEED OF TRUST SATISFACTION", "6623/388", refs=["2418/229"],
           grantors=["ROE, JANE Q"], grantees=["EXAMPLE BANK"], matched=["ROE, JANE Q"]),
    ]
    parcel = {"pin": "9629502113", "pinext": "00000", "owner": "ROE JANE Q", "DeedBook": "6615",
              "DeedPage": "1759", "DeedDate": "20260728", "streetname": "OLD COUNTY HOME",
              "SubName": "", "SubLot": "", "PlatBook": "", "PlatPage": ""}
    search = [{"role": "owner", "subject": me, "grid": _grid(*docs), "complete": True, "narrowed": False}]
    row = {"state": "NC", "county": "Buncombe", "source": "law_firms.hutchens", "listing_type": "foreclosure_sale",
           "case_number": "21SP000271-100", "sale_date": "2026-09-22T00:00:00", "first_seen": "2026-05-12T10:00:00",
           "description": "Hutchens trustee sale, court case 21SP000271-100, deed of trust book/page 2418/229",
           "raw": {"rod_docs": [{"doc_type": "DEED OF TRUST", "book": "2418", "page": "229",
                                "source": "law_firms.hutchens"}]}}
    v, ev = fr.decide(fr.claim_of(row), parcel, search, today=TODAY, owner_rel="agrees", claim_people=[me])
    assert v == "stale" and ev["decided_by"] == "foreclosed_loan_satisfied"
    d = ev["deciding"][0]
    assert d["book_page"] == "6623/388" and d["refs"] == ["2418/229"]
    assert d["tie"] == "claim_cited_dot" and d["tie_strength"] == "exact" and ev["claim_tie"] == "claim_cited_dot"
    assert ev["latest_initiation"]["tie"] == "claim_cited_dot"
    # without the cited loan on the claim the same evidence is the ref chain, weak (what v2 recorded)
    bare = {k: v for k, v in row.items() if k not in ("raw", "description")}
    v, ev = fr.decide(fr.claim_of(bare), parcel, search, today=TODAY, owner_rel="agrees", claim_people=[me])
    assert v == "stale" and ev["deciding"][0]["tie"] == "ref_chain" and ev["deciding"][0]["tie_strength"] == "weak"
    assert "claim_tie" not in ev


# ---------------------------------------------------------------------------------------------
# walls: never a token, stop the run
# ---------------------------------------------------------------------------------------------

def _blocking(resp_for_post):
    r = dict(RESP)
    row = case("parcel:NC:buncombe:9770205617")
    post_keys = [k for k in r if k.startswith("POST ")]
    for k in post_keys:
        r[k] = resp_for_post
    return row, r


@pytest.mark.parametrize("blocked,why", [
    ({"status": 403, "url": fr.SEARCH_URL, "text": "Forbidden"}, "http_403"),
    ({"status": 429, "url": fr.SEARCH_URL, "text": "Too Many Requests"}, "http_429"),
    ({"status": 200, "url": "https://registerofdeeds.buncombenc.gov/External/User/Login.aspx?ReturnUrl=x",
      "text": "<input type=password>"}, "login_redirect"),
    ({"status": 200, "url": fr.SEARCH_URL,
      "text": '<form><textarea name="g-recaptcha-response"></textarea></form>'}, "challenge_page")])
def test_a_block_is_wall_and_stops_the_runs_later_rows(blocked, why):
    row, r = _blocking(blocked)
    client = ReplayFetcher(r)
    res = run(row, client)
    assert res.verdict == "wall" and res.evidence["blocked"] == why and res.evidence["reason"] == "rod_blocked"
    n = len(client.asked)
    res2 = run(case("parcel:NC:buncombe:9701412633"), client)
    assert res2.verdict == "wall" and res2.evidence["reason"] == "rod_blocked_earlier_this_run"
    assert len(client.asked) == n                     # nothing more was asked


def test_the_recaptcha_v3_script_in_every_page_head_is_not_a_challenge():
    boot = RESP[fr.SEARCH_URL]
    page = boot if isinstance(boot, str) else boot["text"]
    assert "recaptcha" in page.lower()
    assert fr.check_block(FormResponse(200, fr.SEARCH_URL, page)) is None


def test_no_body_ever_carries_a_captcha_token():
    body = fr.name_body("DOE", "JANE")
    assert not any("captcha" in k.lower() or "captcha" in str(v).lower() for k, v in body.items())
    assert body[fr._P + "ddlIndexType"] == "CRP"


# ---------------------------------------------------------------------------------------------
# privacy
# ---------------------------------------------------------------------------------------------

def test_no_person_name_in_any_published_evidence():
    """No surname or first name of anyone the row names (owner, defendant, cited grantor) appears
    in the published evidence of its verdict; the ROD parties never do either (the evidence has
    no field that could carry one: public_evidence is a whitelist)."""
    checked = 0
    for c in CASES:
        ev = json.dumps(run(copy.deepcopy(c["row"])).evidence)
        row = c["row"]
        people = []
        for v, sfc in ((row.get("owner_name"), True), (row.get("defendant"), False),
                       ((((row.get("raw") or {}).get("nod")) or {}).get("grantor"), True)):
            people += fr.persons_in(v, surname_first_caps=sfc)
        for last, first, _ in people:
            for tok in (last, first):
                if len(tok) >= 3:
                    checked += 1
                    assert not re.search(r"\b%s\b" % re.escape(tok), ev, re.I), (c["key"], tok)
    assert checked > 100


def test_public_evidence_is_a_whitelist():
    ev = fr.public_evidence("confirmed", {"decided_by": "x", "grantor": "DOE, JANE", "owner": "DOE",
                                          "claim": {"source": "s", "persons": ["DOE"]}})
    assert ev == {"decided_by": "x", "claim": {"source": "s"}}
    assert "human_lane" in fr.public_evidence("unconfirmed", {"reason": "r"})


# ---------------------------------------------------------------------------------------------
# the Fetcher form session (replay side)
# ---------------------------------------------------------------------------------------------

def test_replay_form_session_serves_posts_by_form_key():
    data = {"a": "1", "b": "2"}
    key = form_key("https://h/x", data)
    assert key == form_key("https://h/x", {"b": "2", "a": "1"})
    c = ReplayFetcher({key: {"status": 201, "url": "https://h/y", "text": "ok"}, "https://h/x": "boot"})

    async def go():
        async with c.form_session() as s:
            g = await s.get("https://h/x")
            p = await s.post_form("https://h/x", data)
            with pytest.raises(LookupError):
                await s.post_form("https://h/x", {"a": "other"})
            return g, p
    g, p = asyncio.run(go())
    assert (g.status, g.url, g.text) == (200, "https://h/x", "boot")
    assert (p.status, p.url, p.text) == (201, "https://h/y", "ok")
    assert c.stats()["requests"] == {"h": 3}


# ---------------------------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------------------------

def _vrec(verdict):
    checked = datetime(2026, 10, 6, tzinfo=timezone.utc)
    return {"signal": fr.SIGNAL, "verdict": verdict, "evidence": {}, "source": fr.SOURCE,
            "checked_at": core.iso_z(checked), "verifier_version": fr.VERSION, "verifier": fr._NAME,
            "expires_at": core.iso_z(checked + timedelta(days=fr.TTL_DAYS)), "governs": list(fr.GOVERNS)}


def _row(lt, verification=None):
    raw = {"verification": verification} if verification is not None else {}
    return Listing(source="law_firms.hutchens", source_url="https://x/y", listing_type=lt, state="NC",
                   county="Buncombe", parcel_id="9770205617", street_address="28 PRICE RD",
                   sale_date=datetime(2026, 10, 13), raw=raw)


@pytest.mark.parametrize("lt", [ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS])
@pytest.mark.parametrize("verdict,kept", [("refuted", False), ("stale", False), ("confirmed", True),
                                          ("unconfirmed", True), ("wall", True)])
def test_scoring(lt, verdict, kept):
    names = {n for n, _c, _w in ds._signals_for(_row(lt, [_vrec(verdict)]), today=TODAY)}
    assert (lt.value in names) is kept
    assert lt.value in {n for n, _c, _w in ds._signals_for(_row(lt), today=TODAY)}


# ---------------------------------------------------------------------------------------------
# case-scoped identity
# ---------------------------------------------------------------------------------------------

def test_case_identity_per_claim_on_board_dicts_and_listings():
    v = next(v for v in discover() if v.signal == "foreclosure_rod")
    assert v.identity == "case"
    sp = {"state": "NC", "county": "Buncombe", "source": "law_firms.hutchens",
          "listing_type": "foreclosure_sale", "case_number": "22SP000481-100"}
    li = Listing(source="law_firms.hutchens", source_url="https://x/y",
                 listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Buncombe",
                 case_number="22SP000481-100")
    assert fr.case_identity(sp) == fr.case_identity(li) == fr.case_identity({**sp, "case_number": "22sp000481 100"})
    assert fr.case_identity(sp).startswith("fcrod:") and "481" not in fr.case_identity(sp)
    nod = {"state": "NC", "county": "Buncombe", "source": "counties.nod_discovery", "case_number": "6627/112",
           "listing_type": "lis_pendens",
           "raw": {"nod": {"county": "Buncombe", "book": "6627", "page": "112"}}}
    other = {**nod, "raw": {"nod": {"county": "Cleveland", "book": "6627", "page": "112"}}}
    assert fr.case_identity(nod) != fr.case_identity(other)            # the recording county counts
    no_case = {"state": "NC", "county": "Buncombe", "source": "national.distressed", "listing_type": "lis_pendens"}
    assert fr.case_identity(no_case) and fr.case_identity(no_case) != fr.case_identity({**no_case, "source": "x"})
    # two claims on one parcel are two ledger entries; one claim on two rows of a parcel is one
    a = v.ledger_keys({**sp, "parcel_id": "9701412633"})
    b = v.ledger_keys({**sp, "parcel_id": "9701412633", "street_address": "16 Overlook Drive"})
    c = v.ledger_keys({**sp, "case_number": "26SP000061-100", "parcel_id": "9701412633"})
    assert a[0] == b[0] and a[0] != c[0]


def test_case_identity_is_none_for_rows_it_does_not_cover():
    """The case-scope migration and the VM's apply ask every board row: only this verifier's
    claims may name a case (a case id for every row kept the whole board in memory)."""
    assert fr.case_identity({"state": "NC", "county": "Buncombe", "listing_type": "tax_lien",
                             "case_number": "26CV1"}) is None
    assert fr.case_identity(Listing(source="s", source_url="https://x/y", listing_type=ListingType.AUCTION,
                                    state="NC", county="Buncombe")) is None
