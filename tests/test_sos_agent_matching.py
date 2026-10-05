"""NC SOS result selection + contact parsing + ledger re-check (2026-10-05).

The lookup used to open the FIRST search hit; sosnc.gov's business search is a "Starting With"
search, so a Buncombe "COVENANT PRESBYTERIAN CHURCH" got a Jacksonville church. Everything here
runs against REAL sosnc.gov markup captured live that day (tests/fixtures/sosnc_search_*.html,
the results sections verbatim; tests/fixtures/sosnc_profile_*.txt, profile innerText):

  * parse_search_results() reads the real result list (and finds no location in it)
  * the right result is chosen over the first one (DB Homes, Mill Creek, Asheville West,
    Covenant ... Kannapolis), through _batch_lookup() with a page serving the real markup
  * no confident match -> ambiguous: nothing opened, nothing recorded as resolved, never applied
  * "Not Listed" is no contact; a commercial agent service stays the registered agent, flagged,
    and is never the best contact
  * the ledger re-check rejects first-hit profiles the rule does not stand behind, and the VM
    apply takes a rejected profile off the rows that carry it
No network.
"""
from __future__ import annotations

import asyncio
import copy
import re
import sys
import types
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_sos_agent as sa
from foreclosure_scraper import sos_agent_handoff as ho
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
sys.path.insert(0, str(REPO / "scripts"))


def _html(name: str) -> str:
    return (FIX / f"sosnc_search_{name}.html").read_text(encoding="utf-8")


def _cands(name: str) -> list[dict]:
    return sa.parse_search_results(_html(name))["candidates"]


def _li(owner, raw=None, i=0, state="NC"):
    return Listing(source="x", source_url=f"https://example.test/{i}",
                   listing_type=ListingType.FORECLOSURE_SALE, state=state, county="Buncombe",
                   street_address=f"{i + 1} Main St", zip_code="28801", owner_name=owner,
                   raw=raw or {})


# ---------------------------------------------------------------------------
# the real result list
# ---------------------------------------------------------------------------

def test_parse_real_result_list():
    out = sa.parse_search_results(_html("covenant_presbyterian_church"))
    assert out["records_found"] == 7 and len(out["candidates"]) == 7
    first = out["candidates"][0]
    assert first == {
        "legal_name": "Covenant Presbyterian Church of the Associate Reformed Presbyterian Church",
        "prev_legal_name": "Covenant Presbyterian Church, Independent, Jacksonville, N.C.",
        "sosid": "0281134", "status": "Current - Active", "citizenship": "Domestic",
        "business_type": "Non - Profit Corporation",
        "profile_href": "/online_services/search/Business_Registration_profile/4647514",
    }
    # the list carries no address, city or county field to break a tie on
    for c in out["candidates"]:
        assert set(c) == {"legal_name", "prev_legal_name", "sosid", "status", "citizenship",
                          "business_type", "profile_href"}


def test_unparseable_or_empty_page_has_no_candidates():
    assert sa.parse_search_results("") == {"records_found": None, "candidates": []}
    assert sa.parse_search_results("<html><body>Records Found: 0</body></html>") == \
        {"records_found": 0, "candidates": []}


@pytest.mark.parametrize("a,b", [
    ("BNB PROPERTIES LLC", "BNB Properties, L.L.C."),
    ("ACME L L C", "Acme, LLC"),
    ("DANA HILL CORP", "Dana-hill Corporation"),
    ("NATURE S WAY LANDSCAPING INC", "Nature`s Way Landscaping, Inc."),
    ("J AND M FAMILY HOMES", "J & M Family Homes, Inc."),
    ("CRAYTON FIELDS HOMEOWNERS ASSOCIATION", "Crayton Fields Homeowners' Association"),
    ("BILTMORE CO", "The Biltmore Company"),
    ("ROBERSON LAND DEVELOPMENT CO", "Roberson Land Development Company, LLC"),
    ("PK VENTURES I LP", "Pk Ventures I Limited Partnership"),
    ("SECU RE INC", "SECU*RE, Inc."),
    ("ACME HOLDINGS INCORPORATED", "Acme Holdings, Inc."),
])
def test_names_that_are_the_same_entity(a, b):
    assert sa.names_match(a, b)


@pytest.mark.parametrize("a,b", [
    ("COVENANT PRESBYTERIAN CHURCH",
     "Covenant Presbyterian Church of the Associate Reformed Presbyterian Church"),
    ("COVENANT PRESBYTERIAN CHURCH", "Covenant Presbyterian Church Kannapolis"),
    ("DB HOMES LLC", "DB Homes, Inc."),               # LLC is not a corporation
    ("MILL CREEK PROPERTIES LLC", "Mill Creek Properties, Inc."),
    ("ACME LLC", "Acme Holdings, LLC"),
    ("YORKTOWN FUNDING INC", "Yorktown Funding II, Inc"),
    ("", "Anything LLC"),
])
def test_names_that_are_not(a, b):
    assert not sa.names_match(a, b)


# ---------------------------------------------------------------------------
# selection on the real lists
# ---------------------------------------------------------------------------

def test_right_match_chosen_over_the_first_result():
    c = _cands("db_homes")
    assert c[0]["legal_name"] == "DB Homes, Inc." and c[0]["status"] == "Dissolved"
    pick, d = sa.select_result("DB HOMES LLC", c)
    assert (pick["legal_name"], pick["sosid"]) == ("DB HOMES LLC", "1618927")
    assert d["verdict"] == "match" and d["candidates"] == 5 and d["exact"] == 1

    pick, _ = sa.select_result("MILL CREEK PROPERTIES LLC", _cands("mill_creek_properties"))
    assert (pick["legal_name"], pick["sosid"]) == ("Mill Creek Properties, L.L.C.", "1446137")

    pick, _ = sa.select_result("COVENANT PRESBYTERIAN CHURCH KANNAPOLIS",
                               _cands("covenant_presbyterian_church"))
    assert pick["sosid"] == "1538077"       # 5th of 7


def test_same_name_twins_prefer_the_active_one():
    """'Asheville West, LLC' is registered twice: 0647041 Dissolved (listed first, and the
    profile the board carries) and 1684466 Current - Active."""
    c = _cands("asheville_west")
    assert [x["sosid"] for x in c[:2]] == ["0647041", "1684466"]
    pick, d = sa.select_result("Asheville West, LLC", c)
    assert pick["sosid"] == "1684466" and d["exact"] == 2 and d["active_exact"] == 1


def test_entity_type_decides_between_llc_and_corporation():
    # a name with no designator matches both Mill Creek entities; the active LLC wins
    pick, d = sa.select_result("MILL CREEK PROPERTIES", _cands("mill_creek_properties"))
    assert pick["sosid"] == "1446137" and d["exact"] == 2
    # asking for the corporation gets the corporation, even though it is not active
    pick, d = sa.select_result("Mill Creek Properties, Inc.", _cands("mill_creek_properties"))
    assert pick["sosid"] == "0095863" and d["exact"] == 1


def test_same_designator_type_is_preferred_before_status():
    c = _cands("mill_creek_properties")
    cands = [dict(c[1], legal_name="Mill Creek Properties Company", sosid="1"),   # active
             dict(c[0], legal_name="Mill Creek Properties, L.L.C.", sosid="2")]   # "Multiple"
    pick, d = sa.select_result("MILL CREEK PROPERTIES LLC", cands)
    assert pick["sosid"] == "2" and d["exact"] == 2


def test_no_confident_match_is_ambiguous():
    pick, d = sa.select_result("COVENANT PRESBYTERIAN CHURCH",
                               _cands("covenant_presbyterian_church"))
    assert pick is None
    assert d["verdict"] == "ambiguous" and d["reason"] == "no_exact_name_match"
    assert d["candidates"] == 7 and d["exact"] == 0
    assert d["top"][0].startswith("Covenant Presbyterian Church of the Associate Reformed")
    assert len(d["top"]) == 5


def test_an_unbreakable_tie_is_ambiguous():
    twins = [dict(c, status="Current - Active") for c in _cands("asheville_west")[:2]]
    pick, d = sa.select_result("ASHEVILLE WEST LLC", twins)
    assert pick is None and d["reason"] == "several_exact_matches" and d["exact"] == 2


# ---------------------------------------------------------------------------
# _batch_lookup with a page serving the real markup
# ---------------------------------------------------------------------------

class _FixturePage:
    """A Playwright page for _one(): the search returns a captured results page by search
    core; a profile URL returns the given innerText."""

    def __init__(self, searches: dict[str, str], profiles: dict[str, str], fail=()):
        self.searches, self.profiles, self.fail = searches, profiles, set(fail)
        self.core = None
        self.url = ""
        self.visited: list[str] = []

    async def goto(self, url):
        self.url = url
        self.visited.append(url)

    async def wait_for_selector(self, sel, timeout=0):
        return True

    async def fill(self, sel, value):
        self.core = value
        if value in self.fail:
            raise RuntimeError("Timeout 20000ms exceeded")

    async def eval_on_selector(self, sel, js):
        return None

    async def wait_for_load_state(self, state, timeout=0):
        return None

    async def eval_on_selector_all(self, sel, js):
        return re.findall(r'href="([^"]*business_registration_profile[^"]*)"',
                          self.searches.get(self.core, ""), flags=re.I)

    async def content(self):
        return self.searches.get(self.core, "")

    async def inner_text(self, sel):
        return self.profiles[self.url.rsplit("/", 1)[-1]]

    async def title(self):
        return "Search Results"


def _install(monkeypatch, page):
    async def async_fetch(url, page_action=None, **kw):
        await page_action(page)
    mod = types.ModuleType("scrapling.fetchers")
    mod.StealthyFetcher = types.SimpleNamespace(async_fetch=async_fetch)
    monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", mod)
    monkeypatch.setattr(sa, "_PAUSE_MIN_S", 0.0)
    monkeypatch.setattr(sa, "_PAUSE_MAX_S", 0.0)


_DB_HOMES_LLC_PROFILE = (   # the profile page for 1618927 (innerText shape)
    "Legal name:  DB HOMES LLC\n\nSecretary of State Identification Number (SOSID):  1618927\n"
    "Status:  Current-Active\nCitizenship:  Domestic\nRegistered agent:   Dana Bell\n\n"
    "Registered Office address\n12 Oak St\nAsheville, NC 28801\n\nReturn to top\n")


def test_batch_lookup_opens_the_matching_result_not_the_first(monkeypatch):
    page = _FixturePage({"DB HOMES": _html("db_homes")}, {"13014551": _DB_HOMES_LLC_PROFILE})
    _install(monkeypatch, page)
    oc: dict = {}
    res = asyncio.run(sa._batch_lookup(["DB HOMES LLC"], outcome=oc))
    profile_visits = [u for u in page.visited if "profile" in u.lower()]
    # the 2nd result's profile; the old code opened the 1st (DB Homes, Inc., 5619430)
    assert profile_visits == [sa._BASE + "/online_services/search/Business_Registration_profile/13014551"]
    assert oc["resolved"] == ["DB HOMES LLC"] and oc["ambiguous"] == []
    prof = res["DB HOMES LLC"]
    assert prof["sosid"] == "1618927" and prof["legal_name"] == "DB HOMES LLC"
    assert prof["match_count"] == 5 and prof["exact_matches"] == 1
    assert prof["match_rule"] == sa.MATCH_RULE
    assert prof["best_contact_name"] == "Dana Bell"


def test_batch_lookup_ambiguous_opens_nothing_and_resets_the_breaker(monkeypatch):
    # 5 no-answers, the ambiguous answer, 5 more no-answers: the answer resets the streak, so
    # the 6-in-a-row breaker never trips (an ambiguous answer is the site answering)
    fails = [f"DOWN{i} LLC" for i in range(5)]
    later = [f"LATER{i} LLC" for i in range(5)]
    names = fails + ["COVENANT PRESBYTERIAN CHURCH"] + later
    page = _FixturePage({"COVENANT PRESBYTERIAN CHURCH": _html("covenant_presbyterian_church")},
                        {}, fail=[n.replace(" LLC", "") for n in fails + later])
    _install(monkeypatch, page)
    oc: dict = {}
    res = asyncio.run(sa._batch_lookup(names, outcome=oc))
    assert not [u for u in page.visited if "profile" in u.lower()], "no profile was opened"
    assert res["COVENANT PRESBYTERIAN CHURCH"] is None
    assert oc["ambiguous"] == ["COVENANT PRESBYTERIAN CHURCH"]
    assert oc["resolved"] == [] and oc["misses"] == [] and oc["errors"] == fails + later
    assert oc["attempted"] == 11 and not oc["breaker_tripped"]
    d = oc["ambiguous_detail"]["COVENANT PRESBYTERIAN CHURCH"]
    assert d["candidates"] == 7 and d["exact"] == 0 and d["records_found"] == 7


def test_batch_lookup_rejects_a_profile_page_that_names_another_entity(monkeypatch):
    other = _DB_HOMES_LLC_PROFILE.replace("Legal name:  DB HOMES LLC", "Legal name:  Other LLC")
    page = _FixturePage({"DB HOMES": _html("db_homes")}, {"13014551": other})
    _install(monkeypatch, page)
    oc: dict = {}
    res = asyncio.run(sa._batch_lookup(["DB HOMES LLC"], outcome=oc))
    assert res["DB HOMES LLC"] is None and oc["ambiguous"] == ["DB HOMES LLC"]
    assert oc["ambiguous_detail"]["DB HOMES LLC"]["reason"] == "profile_name_differs"


def test_unreadable_result_list_is_a_no_answer_not_a_miss(monkeypatch):
    page = _FixturePage({"X": '<a href="/online_services/search/Business_Registration_profile/1">'
                              'More information</a>'}, {})
    _install(monkeypatch, page)
    oc: dict = {}
    asyncio.run(sa._batch_lookup(["X LLC"], outcome=oc))
    assert oc["errors"] == ["X LLC"] and oc["misses"] == [] and oc["ambiguous"] == []


# ---------------------------------------------------------------------------
# contact parsing on real profiles
# ---------------------------------------------------------------------------

def test_not_listed_is_no_contact():
    p = sa._parse_profile((FIX / "sosnc_profile_crayton_fields_hoa.txt").read_text())
    assert p["sosid"] == "1589069"
    assert "registered_agent" not in p and "best_contact_name" not in p
    assert p["best_contact_address"] == "155 Garrison Branch Road, Weaverville, NC 28787"
    assert p["agent_is_service"] is False


def test_agent_service_kept_flagged_and_never_the_contact():
    p = sa._parse_profile((FIX / "sosnc_profile_pk_ventures_i_lp.txt").read_text())
    assert p["registered_agent"] == "U S Corporation Co"
    assert p["agent_is_service"] is True
    # its name, its registered office and the mailing address that names it are all the
    # service's mailbox, not the owner's
    assert "best_contact_name" not in p and "best_contact_address" not in p
    assert p["mailing_address"].startswith("U S Corporation Company")


@pytest.mark.parametrize("agent", ["U S Corporation Co", "U.S. Corporation Company",
                                   "C T Corporation System", "Business Filings Incorporated",
                                   "Registered Agents Inc", "The Corporation Trust Company",
                                   "COGENCY GLOBAL INC."])
def test_agent_services_recognised(agent):
    assert sa.is_agent_service(agent)


@pytest.mark.parametrize("person", ["Jeremy Champion", "Sherrye Coggiola", "USA Holdings",
                                    "Dana Bell", ""])
def test_people_are_not_services(person):
    assert not sa.is_agent_service(person)


def test_clean_contact_fixes_stored_profiles_conservatively():
    pk = {"sosid": "0000021", "legal_name": "Pk Ventures I Limited Partnership",
          "registered_agent": "U S Corporation Co", "agent_is_service": False,
          "best_contact_name": "U S Corporation Co",
          "best_contact_address": "327 Hillsborough, Raleigh, NC 27602",
          "registered_office_address": "327 Hillsborough, Raleigh, NC 27602",
          "mailing_address": "U S Corporation Company 229 S State St, Dover, DE 19901"}
    assert sa.clean_contact(pk)
    assert pk["agent_is_service"] is True and pk["registered_agent"] == "U S Corporation Co"
    assert "best_contact_name" not in pk and "best_contact_address" not in pk

    hoa = {"sosid": "1589069", "registered_agent": "Not Listed", "agent_is_service": False,
           "best_contact_name": "Not Listed",
           "best_contact_address": "155 Garrison Branch Road, Weaverville, NC 28787",
           "principal_office_address": "155 Garrison Branch Road, Weaverville, NC 28787"}
    assert sa.clean_contact(hoa)
    assert "registered_agent" not in hoa and "best_contact_name" not in hoa
    assert hoa["best_contact_address"] == "155 Garrison Branch Road, Weaverville, NC 28787"

    good = {"sosid": "1", "registered_agent": "Jane Owner", "best_contact_name": "Legacy Name",
            "best_contact_address": "1 Main St"}
    before = copy.deepcopy(good)
    assert not sa.clean_contact(good) and good == before, "a good legacy profile is untouched"
    assert sa.clean_contact(pk) is False, "idempotent"


# ---------------------------------------------------------------------------
# ledger re-check + statuses
# ---------------------------------------------------------------------------

def _p(legal, sosid, status="Current-Active", match_count=1, **kw):
    d = {"checked": True, "source": "nc_sos", "legal_name": legal, "sosid": sosid,
         "status": status, "match_count": match_count, "agent_is_service": False,
         "registered_agent": "Some Person", "best_contact_name": "Some Person"}
    d.update(kw)
    return d


JACKSONVILLE = _p("Covenant Presbyterian Church of the Associate Reformed Presbyterian Church",
                  "0281134", match_count=7, resolved_for_entity="COVENANT PRESBYTERIAN CHURCH",
                  resolved_at="2026-10-05", profile_url="https://www.sosnc.gov/.../4647514")
DB_INC = _p("DB Homes, Inc.", "0665525", status="Dissolved", match_count=5)
AW_DISSOLVED = _p("Asheville West, LLC", "0647041", status="Dissolved", match_count=4)


def _ledger_like_the_real_one() -> dict:
    ents: dict = {}
    ho.record_result(ents, "COVENANT PRESBYTERIAN CHURCH", "resolved", JACKSONVILLE,
                     today="2026-10-05")
    for name, prof in [("DB HOMES LLC", DB_INC), ("DB Homes, Inc.", DB_INC),
                       ("Asheville West, LLC", AW_DISSOLVED),
                       ("Crayton Fields Homeowners' Association",
                        _p("Crayton Fields Homeowners' Association", "1589069",
                           registered_agent="Not Listed", best_contact_name="Not Listed",
                           best_contact_address="155 Garrison Branch Road",
                           principal_office_address="155 Garrison Branch Road")),
                       ("Good Holdings, LLC", _p("Good Holdings, LLC", "5")),
                       ("Twin Ok, LLC", _p("Twin Ok, LLC", "6", status="Current-Active",
                                           match_count=3)),
                       ("Picked Ok, LLC", _p("Picked Ok, LLC", "7", status="Dissolved",
                                             match_count=3, match_rule=sa.MATCH_RULE))]:
        e = ho.record_result(ents, name, "resolved", prof, today="2026-09-01",
                             source="board_seed")
        e["checks"] = 0
    return ents


def test_recheck_rejects_what_the_rule_does_not_stand_behind():
    ents = _ledger_like_the_real_one()
    rc = ho.recheck_resolved(ents, today="2026-10-05")
    assert sorted(rc["mismatch"]) == ["asheville west llc", "covenant presbyterian church",
                                      "db homes inc", "db homes llc"]
    assert rc["by_reason"] == {"legal_name_differs": 2, "inactive_first_hit": 2}
    cov = ents["covenant presbyterian church"]
    assert cov["status"] == "mismatch" and "profile" not in cov
    assert cov["rejected_profile"]["sosid"] == "0281134" and cov["rejected_sosids"] == ["0281134"]
    assert cov["mismatch"] == {"reason": "legal_name_differs", "at": "2026-10-05",
                               "legal_name": JACKSONVILLE["legal_name"], "sosid": "0281134",
                               "match_count": 7}
    for k in ("good holdings llc", "twin ok llc", "picked ok llc"):
        assert ents[k]["status"] == "resolved", k
    assert rc["contacts_cleaned"] == ["crayton fields homeowners association"]
    assert ents["crayton fields homeowners association"]["profile"].get("best_contact_name") is None
    # idempotent
    again = ho.recheck_resolved(ents, today="2026-10-06")
    assert again["mismatch"] == [] and again["contacts_cleaned"] == []
    c = ho.ledger_counts(ents)
    assert c["mismatch"] == 4 and c["resolved"] == 4


def test_a_mismatch_is_never_applied_and_is_re_queried_first():
    ents = _ledger_like_the_real_one()
    ho.recheck_resolved(ents, today="2026-10-05")
    assert "covenant presbyterian church" not in ho.resolved_profiles({"entities": ents})
    assert ho.is_due(ents["covenant presbyterian church"], "2026-10-05")
    import sos_agent_refresh as sar
    cand = {"good new llc": {"name": "GOOD NEW LLC", "prio": 0, "order": 0, "rows": 1},
            "covenant presbyterian church": {"name": "COVENANT PRESBYTERIAN CHURCH", "prio": 2,
                                             "order": 1, "rows": 2}}
    tg = sar.pick_targets(cand, ents, cap=1, today="2026-10-05")
    assert tg["names"] == ["COVENANT PRESBYTERIAN CHURCH"] and tg["requeries"] == 1


def test_what_a_re_query_does_to_a_mismatch():
    ents = _ledger_like_the_real_one()
    ho.recheck_resolved(ents, today="2026-10-05")
    # no answer: still a mismatch, retried after the no-answer wait
    ho.record_result(ents, "COVENANT PRESBYTERIAN CHURCH", "error", today="2026-10-06")
    assert ents["covenant presbyterian church"]["status"] == "mismatch"
    # ambiguous: recorded with its detail, never applied
    ho.record_result(ents, "COVENANT PRESBYTERIAN CHURCH", "ambiguous", today="2026-10-09",
                     detail={"reason": "no_exact_name_match", "candidates": 7, "exact": 0})
    cov = ents["covenant presbyterian church"]
    assert cov["status"] == "ambiguous" and cov["ambiguity"]["candidates"] == 7
    assert "profile" not in cov and cov["rejected_sosids"] == ["0281134"]
    assert not ho.is_due(cov, "2026-10-20") and ho.is_due(cov, "2026-11-08")
    # the right entity found: resolved with the new profile; the rejected SOSID stays recorded
    good = _p("DB HOMES LLC", "1618927", match_count=5, match_rule=sa.MATCH_RULE)
    ho.record_result(ents, "DB HOMES LLC", "resolved", good, today="2026-10-06")
    db = ents["db homes llc"]
    assert db["status"] == "resolved" and db["profile"]["sosid"] == "1618927"
    assert db["rejected_sosids"] == ["0665525"]
    assert ho.recheck_resolved(ents, today="2026-10-06")["mismatch"] == []


def test_a_rejected_profile_still_on_the_board_never_re_seeds():
    ents = _ledger_like_the_real_one()
    ho.recheck_resolved(ents, today="2026-10-05")
    assert ho.seed_names_for_board_profile(JACKSONVILLE, "COVENANT PRESBYTERIAN CHURCH") == []
    assert ho.seed_from_board_profile(ents, JACKSONVILLE, "COVENANT PRESBYTERIAN CHURCH") == 0
    assert ho.seed_from_board_profile(ents, DB_INC, "DB HOMES LLC") == 0
    assert ho.seed_from_board_profile(ents, AW_DISSOLVED, "ASHEVILLE WEST LLC") == 0
    assert ents["covenant presbyterian church"]["status"] == "mismatch"
    assert ents["asheville west llc"]["status"] == "mismatch"


def test_merge_never_resurrects_a_rejected_profile():
    disk = {"entities": _ledger_like_the_real_one()}            # not yet re-checked
    mem = {"entities": copy.deepcopy(disk["entities"])}
    ho.recheck_resolved(mem["entities"], today="2026-10-05")
    ho.merge_ledgers(mem, disk)
    cov = mem["entities"]["covenant presbyterian church"]
    assert cov["status"] == "mismatch" and "profile" not in cov
    assert cov["mismatch"]["reason"] == "legal_name_differs"
    assert ho.recheck_resolved(mem["entities"], today="2026-10-05")["mismatch"] == []


def test_a_re_query_that_confirms_the_same_entity_restores_it():
    """Asheville-West-style: rejected as an inactive first hit, then the new rule picks the
    same SOSID (the only same-name entity). It is applied again, and not cleared from rows."""
    ents = _ledger_like_the_real_one()
    ho.recheck_resolved(ents, today="2026-10-05")
    again = dict(DB_INC, match_rule=sa.MATCH_RULE, exact_matches=1)
    ho.record_result(ents, "DB Homes, Inc.", "resolved", again, today="2026-10-06")
    assert ho.recheck_resolved(ents, today="2026-10-06")["mismatch"] == []
    assert ho.resolved_profiles({"entities": ents})["db homes inc"]["sosid"] == "0665525"
    assert "db homes inc" not in ho.rejected_sosids_by_key({"entities": ents}).get("0665525", set())
    older = {"entities": _ledger_like_the_real_one()}
    ho.recheck_resolved(older["entities"], today="2026-10-05")
    ho.merge_ledgers(older, {"entities": ents})
    assert older["entities"]["db homes inc"]["status"] == "resolved"
    assert older["entities"]["db homes inc"]["profile"]["match_rule"] == sa.MATCH_RULE


# ---------------------------------------------------------------------------
# VM apply clears rejected profiles from the rows that carry them
# ---------------------------------------------------------------------------

def _save(tmp_path, ents) -> Path:
    led = ho.empty_ledger()
    led["entities"] = ents
    p = tmp_path / "sos_agent_results.json"
    ho.save_ledger(led, p, host="mac")
    return p


@pytest.mark.parametrize("rechecked", [True, False])
def test_vm_apply_clears_mismatched_profiles(tmp_path, rechecked):
    ents = _ledger_like_the_real_one()
    if rechecked:
        ho.recheck_resolved(ents, today="2026-10-05")
        good = _p("DB HOMES LLC", "1618927", match_count=5, match_rule=sa.MATCH_RULE,
                  best_contact_name="Dana Bell")
        ho.record_result(ents, "DB HOMES LLC", "resolved", good, today="2026-10-06")
    p = _save(tmp_path, ents)
    legacy_db = {k: v for k, v in DB_INC.items()}             # legacy: no resolved_for_entity
    rows = [
        _li("COVENANT PRESBYTERIAN CHURCH", raw={"sos_agent": copy.deepcopy(JACKSONVILLE)}, i=0),
        _li("COVENANT PRESBYTERIAN CHURCH", i=1),
        # the Jacksonville church's own row keeps its (right) profile
        _li("Covenant Presbyterian Church of the Associate Reformed Presbyterian Church", i=2,
            raw={"sos_agent": dict(JACKSONVILLE, resolved_for_entity=JACKSONVILLE["legal_name"])}),
        _li("DB HOMES LLC", raw={"sos_agent": copy.deepcopy(legacy_db)}, i=3),
        # docs/HANDOFF.md item 57: the owner changed after the lookup -- not this step's call
        _li("TRIVETTE, BRUCE", raw={"sos_agent": copy.deepcopy(legacy_db)}, i=4),
        _li("Crayton Fields Homeowners Association", i=5, raw={"sos_agent": {
            "sosid": "1589069", "registered_agent": "Not Listed",
            "best_contact_name": "Not Listed", "best_contact_address": "155 Garrison Branch Road"}}),
        _li("Good Holdings LLC", i=6),
    ]
    out = ho.apply_sos_agent_handoff(rows, path=p)
    assert out["status"] == "ok"
    assert "sos_agent" not in rows[0].raw and "sos_agent" not in rows[1].raw
    assert rows[2].raw["sos_agent"]["sosid"] == "0281134"
    assert rows[4].raw["sos_agent"]["sosid"] == "0665525"
    assert rows[5].raw["sos_agent"].get("best_contact_name") is None
    assert "registered_agent" not in rows[5].raw["sos_agent"]
    assert rows[6].raw["sos_agent"]["sosid"] == "5"
    if rechecked:
        # cleared, then given the confirmed profile in the same pass
        assert rows[3].raw["sos_agent"]["sosid"] == "1618927"
        assert out["cleared"] == 2 and out["attached"] == 2
    else:
        # a ledger the Mac has not re-checked: the VM's own check still refuses it
        assert "sos_agent" not in rows[3].raw
        assert out["cleared"] == 2 and out["attached"] == 1
    assert out["cleaned"] == 1


def test_mac_scan_counts_rows_carrying_a_rejected_profile_as_candidates(tmp_path, monkeypatch):
    import sos_agent_refresh as sar
    ents = _ledger_like_the_real_one()
    ho.recheck_resolved(ents, today="2026-10-05")
    recs = [{"state": "NC", "owner_name": "COVENANT PRESBYTERIAN CHURCH", "defendant": None,
             "raw": {"sos_agent": copy.deepcopy(JACKSONVILLE)}},
            {"state": "NC", "owner_name": "GOOD HOLDINGS LLC", "defendant": None,
             "raw": {"sos_agent": _p("Good Holdings, LLC", "5")}}]
    monkeypatch.setattr(sar, "iter_board_rows", lambda path: iter(recs))
    scan = sar.scan_board(tmp_path, ents, "2026-10-05")
    assert scan["carrying_rejected"] == 1
    assert set(scan["candidates"]) == {"covenant presbyterian church"}
