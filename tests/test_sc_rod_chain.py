"""Offline tests for the shared SC register chain builder (rod/sc_chain.py) and the polite,
wall-aware HTTP layer (rod/sc_polite.py). Every name here is made up."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from foreclosure_scraper.rod import sc_chain, sc_polite
from foreclosure_scraper.rod.models import RodDoc
from foreclosure_scraper.rod.sc_chain import (NameQuery, build_chain, index_query, kind_of, name_fit,
                                              owner_query, run_chain, run_search)
from foreclosure_scraper.rod.sc_polite import LookupBudget, PoliteSession, RodWalled, detect_wall


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    sc_polite.reset_walled()
    sc_chain.clear_cache()
    monkeypatch.setattr(sc_polite, "SLEEP", lambda s: None)
    yield
    sc_polite.reset_walled()


def doc(day: str, typ: str, grantor: str, grantee: str, book: str, page: str, desc: str = "") -> RodDoc:
    return RodDoc(county="Testcounty", state="SC", doc_type=typ,
                  recorded_date=datetime.strptime(day, "%Y-%m-%d"), book=book, page=page,
                  grantor=grantor, grantee=grantee, notes=desc or None, raw={"doc_type_label": typ})


# -- names ------------------------------------------------------------------------------------
def test_owner_query_both_conventions():
    a = owner_query("QUILLFEATHER ROSALIND M & QUILLFEATHER OTIS")
    b = owner_query("Rosalind M Quillfeather")
    assert (a.last, a.first, a.middle) == ("QUILLFEATHER", "ROSALIND", "M")
    assert (b.last, b.first, b.middle) == ("QUILLFEATHER", "ROSALIND", "M")
    assert a.term == "QUILLFEATHER ROSALIND"


def test_entity_query_drops_form_words():
    q = owner_query("Larkspur Meadow Homes, L.L.C.")
    assert q.entity and q.term == "LARKSPUR MEADOW HOMES"
    assert name_fit(q, "LARKSPUR MEADOW HOMES LLC") == "full"
    assert name_fit(q, "LARKSPUR MEADOW") == "compatible"
    assert name_fit(q, "LARKSPUR PINES LLC") is None


def test_name_fit_rules():
    q = owner_query("QUILLFEATHER ROSALIND M")
    assert name_fit(q, "QUILLFEATHER ROSALIND M") == "full"
    assert name_fit(q, "<em>QUILLFEATHER</em> ROSALIND MAE") == "full"
    assert name_fit(q, "QUILLFEATHER R") == "compatible"            # initial
    assert name_fit(q, "QUILLFEATHER ROSALIND") == "compatible"     # middle missing
    assert name_fit(q, "QUILLFEATHER ROSALIND T") is None          # middle conflicts
    assert name_fit(q, "QUILLFEATHER ROSAMUND M") is None
    assert name_fit(q, "QUILLFEATHER, ROSALIND M JR") == "full"     # comma + suffix
    assert name_fit(q, "TESTBANK OF NOWHERE NA") is None


def test_index_query_reads_surname_first():
    q = index_query("BRAMBLEWOOD OTIS T")
    assert (q.last, q.first, q.middle) == ("BRAMBLEWOOD", "OTIS", "T")


@pytest.mark.parametrize("label,kind", [
    ("DEED", "deed"), ("QUIT-CLAIM DEED", "deed"), ("DEED OF DISTRIBUTION", "deed"),
    ("MORTGAGE", "mortgage"), ("SATISFACTION OF MORTGAGE", "satisfaction"),
    ("SATISFACTION MORTGAGE", "satisfaction"), ("PARTIAL RELEASE", "satisfaction"),
    ("ASSIGNMENT OF MORTGAGE", "other"), ("LIS PENDENS", "lis_pendens"),
    ("LIS PENDENS MTG RELEASE", "lis_pendens_release"), ("MECHANICS LIEN", "lien"),
    ("NOTICE OF LIEN", "lien"), ("TAX LIENS - STATE", "lien"), ("JUDGMENT", "lien"),
    ("RELEASE OF LIEN", "lien_release"), ("POWER OF ATTORNEY", "other"), ("EASEMENT", "other"),
    ("DEED OF TRUST", "mortgage"), ("DEED (TIMESHARE)", "other"), ("PLAT", "other"),
])
def test_kind_of(label, kind):
    assert kind_of(doc("2020-01-01", label, "A B", "C D", "1", "1")) == kind


# -- the chain --------------------------------------------------------------------------------
OWNER = "QUILLFEATHER ROSALIND M"
SELLER = "BRAMBLEWOOD OTIS T"
EARLIER = "FENWICK HOLLOWAY LLC"


def fake_register(calls: list):
    """A searcher over a tiny made-up register."""
    owner_docs = [
        doc("2019-05-02", "DEED", SELLER, OWNER, "2100", "10", "LOT 7 MAPLE RUN"),
        doc("2019-05-02", "MORTGAGE", OWNER, "TESTBANK OF NOWHERE NA", "5000", "200"),
        doc("2021-08-11", "SATISFACTION OF MORTGAGE", OWNER, "TESTBANK OF NOWHERE NA", "SAT9", "3"),
        doc("2022-03-01", "MORTGAGE", OWNER, "SECOND TESTBANK", "5300", "40"),
        doc("2024-06-30", "LIS PENDENS", "SECOND TESTBANK", OWNER, "LP1", "77"),
        doc("2010-01-15", "MORTGAGE", "QUILLFEATHER ROSALIND T", "OTHER BANK", "4000", "1"),  # other person
    ]
    seller_docs = [
        doc("2012-09-09", "DEED", EARLIER, SELLER, "1800", "55", "LOT 7 MAPLE RUN"),
        doc("2019-05-02", "DEED", SELLER, OWNER, "2100", "10"),        # the deed itself: excluded
        doc("2023-01-01", "DEED", "SOMEONE", SELLER, "2300", "1"),      # after the date: excluded
    ]
    entity_docs = [doc("2001-02-03", "DEED", "ACORN TRUST", EARLIER, "900", "9")]

    def search(q: NameQuery, side: str, date_to):
        calls.append((q.term, side, date_to))
        if q.term == "QUILLFEATHER ROSALIND":
            return owner_docs
        if q.term == "BRAMBLEWOOD OTIS":
            return seller_docs
        if q.term == "FENWICK HOLLOWAY":
            return entity_docs
        return []
    return search


def test_build_chain_full_structure():
    calls: list = []
    res = build_chain(fake_register(calls), state="SC", county="Testcounty", owner_name=OWNER,
                      platform="test", max_prior=3)
    d = res.to_dict()
    assert d["status"] == "ok" and d["reason"] is None and d["owner_searched"] == OWNER
    ld = d["last_deed"]
    assert ld["book"] == "2100" and ld["page"] == "10" and ld["recorded"] == "2019-05-02"
    assert ld["type"] == "DEED" and ld["kind"] == "deed"
    assert ld["grantors"] == [SELLER] and ld["grantees"] == [OWNER] and ld["description"] == "LOT 7 MAPLE RUN"
    assert [p["book"] for p in d["prior_instruments"]] == ["1800", "900"]
    assert d["prior_instruments"][0]["tie"].startswith("grantee BRAMBLEWOOD OTIS T is the grantor")
    # liens: the other person's 2010 mortgage (middle T) is not the owner's
    liens = d["liens"]
    assert [m["book"] for m in liens["deeds_of_trust"]] == ["5300", "5000"]
    assert all(m["kind"] == "mortgage" for m in liens["deeds_of_trust"])
    assert len(liens["satisfactions"]) == 1 and len(liens["lis_pendens"]) == 1
    assert liens["open_deeds_of_trust_est"] == 1 and liens["since"] == "2019-05-02"
    s = liens["summary"]
    assert s["mortgages_since_last_deed"] == 2 and s["satisfactions_since_last_deed"] == 1
    assert s["open_mortgages_est"] == 1 and s["lis_pendens_open_est"] == 1
    assert d["owner_instruments"] == 5 and d["searches"] == 4
    # owner both sides, then grantee-only searches bounded by each deed's date
    assert calls[0][1] == "both"
    assert calls[1] == ("BRAMBLEWOOD OTIS", "grantee", date(2019, 5, 2))
    assert calls[2] == ("FENWICK HOLLOWAY", "grantee", date(2012, 9, 9))
    assert d["chain_stopped"].startswith("No earlier deed into ACORN TRUST")


def test_build_chain_stops_at_max_prior():
    res = build_chain(fake_register([]), state="SC", county="Testcounty", owner_name=OWNER,
                      platform="test", max_prior=1)
    assert len(res.prior) == 1
    assert any("by design" in n for n in res.notes)


def test_build_chain_empty_register():
    res = build_chain(lambda q, s, d: [], state="SC", county="Testcounty", owner_name=OWNER, platform="test")
    assert res.last_deed is None and res.prior == [] and res.mortgages == []
    assert res.status == "not_found" and res.to_dict()["status"] == "not_found"


def test_build_chain_wall_stops_without_retry():
    calls = []

    def walled(q, side, d):
        calls.append(1)
        raise RodWalled("https://example.test/search", "CAPTCHA")
    res = build_chain(walled, state="SC", county="Testcounty", owner_name=OWNER, platform="test")
    assert res.walled and res.wall_reason == "CAPTCHA" and len(calls) == 1
    assert res.status == "walled" and res.reason == "CAPTCHA"


def test_master_in_equity_deed_stops_chain():
    def reg(q, side, d):
        return [doc("2018-01-01", "MASTER IN EQUITY DEED", "MASTER IN EQUITY FOR TESTCOUNTY", OWNER, "9", "9")]
    res = build_chain(reg, state="SC", county="Testcounty", owner_name=OWNER, platform="test")
    assert res.last_deed is not None and res.prior == []
    assert "forced sale" in res.chain_stopped


def test_run_chain_records_wall_and_never_calls_again():
    made = []

    def factory():
        made.append(1)

        def s(q, side, d):
            raise RodWalled("https://example.test/", "challenge page")
        return s
    b = LookupBudget(cap=10)
    first = run_chain(platform="t", state="SC", county="Wallcounty", owner_name=OWNER, make_searcher=factory, budget=b)
    second = run_chain(platform="t", state="SC", county="Wallcounty", owner_name=OWNER, make_searcher=factory, budget=b)
    assert first.walled and sc_polite.walled_reason("SC", "Wallcounty") == "challenge page"
    assert second.walled and second.skipped == "county walled earlier this run"
    assert made == [1]                       # the second lookup never built a session


def test_run_chain_cap_per_county():
    b = LookupBudget(cap=1)
    f = lambda: (lambda q, s, d: [])  # noqa: E731
    a = run_chain(platform="t", state="SC", county="Capcounty", owner_name=OWNER, make_searcher=f, budget=b)
    c = run_chain(platform="t", state="SC", county="Capcounty", owner_name=SELLER, make_searcher=f, budget=b)
    assert a.skipped is None and c.skipped.startswith("lookup cap reached") and c.status == "capped"


def test_cache_shares_the_owner_search_between_enrichers():
    built = []

    def factory():
        built.append(1)
        return fake_register([])
    b = LookupBudget(cap=1)
    docs = run_search(platform="t", state="SC", county="Cachecounty", name=OWNER, make_searcher=factory, budget=b)
    res = run_chain(platform="t", state="SC", county="Cachecounty", owner_name=OWNER, make_searcher=factory, budget=b)
    assert docs and res.status == "ok"          # the chain ran although the cap (1) was spent
    assert b.used[("SC", "cachecounty")] == 1


def test_run_search_failure_is_empty_not_walled():
    def factory():
        def s(q, side, d):
            raise RuntimeError("HTTP 500 error page")
        return s
    assert run_search(state="SC", county="Errcounty", name=OWNER, make_searcher=factory,
                      budget=LookupBudget(cap=5)) == []
    assert sc_polite.walled_reason("SC", "Errcounty") is None


# -- sc_polite --------------------------------------------------------------------------------
@pytest.mark.parametrize("status,text,why", [
    (200, "<html><title>Just a moment...</title></html>", "challenge page"),
    (200, '<div class="g-recaptcha" data-sitekey="x"></div>', "CAPTCHA"),
    (200, '<input type="hidden" name="ctl00$hdnBotResult" id="ctl00_hdnBotResult" />', "bot check"),
    (403, "", "HTTP 403"),
    (429, "slow down", "HTTP 429"),
    (200, "<title>Access Denied</title>", "block page"),
])
def test_detect_wall(status, text, why):
    assert detect_wall(status, "https://example.test/search", text) == why


def test_detect_wall_plain_pages():
    assert detect_wall(200, "https://example.test/NameSearch.php", "<table>rows</table>") is None
    assert detect_wall(500, "https://example.test/x", "Internal Server Error") is None


class _FakeResp:
    def __init__(self, status=200, text="ok", url="https://pace.test/"):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


class _FakeSession:
    def __init__(self, resp=None):
        self.resp = resp or _FakeResp()
        self.calls = 0

    def request(self, method, url, **kw):
        self.calls += 1
        return self.resp


def test_polite_session_paces_same_host():
    waits = []
    clock = iter([0.0, 0.0, 0.1, 0.1, 0.2, 0.2]).__next__
    ps = PoliteSession(session=_FakeSession(), sleep=waits.append, clock=clock)
    sc_polite._host_last.pop("pace.test", None)
    ps.get("https://pace.test/a")
    ps.get("https://pace.test/b")
    assert waits and waits[0] >= 1.6 - 0.1


def test_polite_session_raises_on_wall():
    ps = PoliteSession(session=_FakeSession(_FakeResp(200, "<title>Just a moment...</title>")))
    with pytest.raises(RodWalled):
        ps.get("https://wall.test/")


def test_min_gap_floor():
    assert sc_polite.MIN_GAP_S >= 1.6


def test_failed_chain_step_keeps_the_last_deed():
    def reg(q, side, d):
        if q.term == "QUILLFEATHER ROSALIND":
            return [doc("2019-05-02", "DEED", SELLER, OWNER, "2100", "10")]
        raise TimeoutError("read timed out")
    res = build_chain(reg, state="SC", county="Testcounty", owner_name=OWNER, platform="test")
    assert res.status == "ok" and res.last_deed.book == "2100" and res.prior == []
    assert "did not answer" in res.chain_stopped
