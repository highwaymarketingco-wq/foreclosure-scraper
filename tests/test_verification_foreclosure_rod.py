"""The foreclosure_rod verifier (verification/verifiers/foreclosure_rod_buncombe.py): Buncombe NC
lis_pendens / foreclosure_sale rows against the Register of Deeds instrument chain of the board's
own parcel, and the Fetcher form sessions it fetches through.

What these pin:
  * the 84 live verdicts of 2026-10-06 (VERSION v2, docs/handoff/verification/foreclosure_rod.json)
    reproduce exactly from the sweep's own responses (tests/fixtures/verification/
    foreclosure_rod_buncombe.json.gz: the county parcel layer's JSON and the ROD result pages,
    reduced to the grid and PSEUDONYMIZED, one name mapping throughout, middle initials,
    descriptions, book/pages, refs, dates and types kept; foreclosure_rod_cases.json: the rows);
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

def test_every_live_verdict_reproduces_from_the_captured_responses():
    assert len(CASES) == 84
    got = Counter()
    for c in CASES:
        res = run(copy.deepcopy(c["row"]))
        assert (res.verdict, res.evidence.get("decided_by"), res.evidence.get("reason")) == \
            (c["verdict"], c["decided_by"], c["reason"]), c["key"]
        got[res.verdict] += 1
    assert got == {"unconfirmed": 59, "confirmed": 18, "stale": 6, "refuted": 1}


def test_the_registry_finds_it_with_its_contract():
    v = next(v for v in discover() if v.signal == "foreclosure_rod")
    assert v.name == "foreclosure_rod_buncombe" and v.version == fr.VERSION
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


def test_stale_the_trustee_deed_that_ends_the_confirming_chain():
    """16 Saxon Hl: only a street tie, but the trustee deed refers to the same deed of trust as the
    substitute-trustee appointment that would otherwise confirm, and is younger than the county
    layer's lag."""
    ev = _ev("parcel:NC:buncombe:9685484456")
    assert ev["decided_by"] == "trustee_deed_recorded" and ev["ends_initiation"] is True
    assert ev["deciding"][0]["tie_strength"] == "weak"


def test_stale_judged_against_the_borrowers_acquisition_not_the_later_buyers():
    """1410 Double Knob Loop: trustee deed to the lender 2026-04-27, the lender's resale 2026-09-08."""
    ev = _ev("parcel:NC:buncombe:9623271978")
    assert ev["decided_by"] == "trustee_deed_recorded" and ev["county_layer_agrees"] is True
    assert ev["claim_person_among_grantors"] in ("agrees", "unverified")


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
