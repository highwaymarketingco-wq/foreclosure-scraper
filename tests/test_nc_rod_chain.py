"""The shared NC register layer (rod/nc_polite.py, rod/nc_chain.py) on made-up names: instrument
classification, owner-name parsing and matching, wall detection, pacing, the per-county lookup
cap, and the chain walk with its stop reasons. No network."""
from __future__ import annotations

import pytest

from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import (DEED, DEED_OF_TRUST, FORECLOSURE, LIS_PENDENS, OTHER_KIND, SATISFACTION,
                                              SUBSTITUTION, ASSIGNMENT, IndexRecord, SearchResult, build_chain,
                                              classify_kind, merge_records, parse_owner, same_party)
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, FakeResp, install


@pytest.mark.parametrize("label,category,kind", [
    ("DEED", None, DEED), ("WARRANTY DEED", None, DEED), ("D", None, DEED), ("QD", "DEED", DEED),
    ("TR/D", None, DEED), ("SUBSTITUTE TRUSTEES DEED", None, DEED),
    ("D/T", None, DEED_OF_TRUST), ("DT", None, DEED_OF_TRUST), ("D T", None, DEED_OF_TRUST),
    ("DEED OF TRUST", None, DEED_OF_TRUST), ("CAN D T", None, SATISFACTION),
    ("SAT D/T", None, SATISFACTION), ("CAN D/T", None, SATISFACTION), ("SATISFACTION", None, SATISFACTION),
    ("SF", "CANCELLATION", SATISFACTION),
    ("S/T", None, SUBSTITUTION), ("SUBSTITUTION OF TRUSTEE", None, SUBSTITUTION), ("SUB TR", None, SUBSTITUTION),
    ("LIS PENDENS", None, LIS_PENDENS), ("LIS/P", None, LIS_PENDENS), ("LP", "OTHER", LIS_PENDENS),
    ("FORCL", None, FORECLOSURE), ("NOTICE OF FORECLOSURE SALE", None, FORECLOSURE),
    ("ASSGN", None, ASSIGNMENT), ("ASSIGNMENT", None, ASSIGNMENT),
    ("D-T", None, DEED_OF_TRUST), ("LIS-P", None, LIS_PENDENS), ("D-REL", None, SATISFACTION), ("S-T", None, SUBSTITUTION),
    ("TR-D", None, DEED), ("P-A", None, OTHER_KIND),
    ("MODIFICATION OF DEED OF TRUST", None, OTHER_KIND), ("P A", None, OTHER_KIND), ("EASEMENT", None, OTHER_KIND),
])
def test_classify_kind(label, category, kind):
    assert classify_kind(label, category) == kind


def test_parse_owner_both_conventions_and_entities():
    o = parse_owner("TESTER ALVIN Q")
    assert (o.last, o.first, o.middle, o.entity) == ("TESTER", "ALVIN", "Q", False)
    o = parse_owner("Alvin Q Tester")
    assert (o.last, o.first) == ("TESTER", "ALVIN")
    o = parse_owner("TESTER, ALVIN & BERTHA")
    assert (o.last, o.first) == ("TESTER", "ALVIN")
    o = parse_owner("Example Holdings, LLC")
    assert o.entity and o.last == "EXAMPLE HOLDINGS LLC"
    assert parse_owner("") is None and parse_owner(None) is None


def test_same_party():
    o = parse_owner("TESTER ALVIN Q")
    assert same_party(o, "TESTER, ALVIN QUINCY")
    assert same_party(o, "TESTER ALVIN")
    assert same_party(o, "TESTER, A")                  # an initial in the index
    assert not same_party(o, "TESTER, BERTHA")
    assert not same_party(o, "TESTERSON, ALVIN")
    assert not same_party(o, "EXAMPLE HOLDINGS LLC")
    e = parse_owner("EXAMPLE HOLDINGS LLC")
    assert same_party(e, "EXAMPLE HOLDINGS, LLC")
    assert not same_party(e, "TESTER, ALVIN")


def test_merge_records_folds_party_rows():
    a = IndexRecord(recorded="2020-01-02", book="10", page="20", doc_type="DEED", grantors=["TESTER, ALVIN"],
                    grantees=["SAMPLE, CORA"])
    b = IndexRecord(recorded="2020-01-02", book="10", page="20", doc_type="DEED", grantors=["TESTER, BERTHA"],
                    grantees=["SAMPLE, CORA"], description="LOT 1 EXAMPLE ACRES")
    out = merge_records([a, b])
    assert len(out) == 1
    assert out[0].grantors == ["TESTER, ALVIN", "TESTER, BERTHA"]
    assert out[0].description == "LOT 1 EXAMPLE ACRES"


# -- walls, pacing, budget --------------------------------------------------------------------

LOGIN_PAGE = FakeResp("<html><head><title>eSearch | Account Sign In</title></head><body>"
                      "<input name='ctl00$cphMain$blkLogin$txtUsername' type='text'/>"
                      "<input name='ctl00$cphMain$blkLogin$txtPassword' type='password'/>"
                      "<input type='submit' name='ctl00$cphMain$blkLogin$btnGuestLogin' value='Sign in as a Guest'/>"
                      "</body></html>", 200, "https://example.test/tenant/User/Login.aspx?ReturnUrl=x")


def test_wall_reason_on_canned_pages():
    assert nc_polite.wall_reason(403, "https://x.test/a", CLOUDFLARE_403.text) == "HTTP 403"
    assert nc_polite.wall_reason(200, "https://x.test/a", CLOUDFLARE_403.text) == "challenge page"
    assert nc_polite.wall_reason(200, "https://x.test/a", CAPTCHA_PAGE.text) == "CAPTCHA"
    assert nc_polite.wall_reason(200, LOGIN_PAGE.url, LOGIN_PAGE.text) == "login page"
    assert nc_polite.wall_reason(503, "https://x.test/a", "") == "HTTP 503"
    assert nc_polite.wall_reason(200, "https://x.test/a", "<html><title>The Lookup</title></html>") is None


def test_pacing_waits_between_requests_to_one_host(monkeypatch):
    install(monkeypatch, [("GET", "a.test", FakeResp("ok"))])
    t = {"now": 100.0}
    slept: list[float] = []
    monkeypatch.setattr(nc_polite, "clock", lambda: t["now"])
    monkeypatch.setattr(nc_polite, "sleep", lambda s: slept.append(s))
    c = nc_polite.PoliteClient("p", "NC", "Testco")
    c.get("https://a.test/1")
    t["now"] += 0.5
    c.get("https://a.test/2")
    assert slept and abs(slept[0] - 1.1) < 1e-6           # 1.6 s gap, 0.5 s already gone
    c.get("https://b.test/1")                             # another host: no wait
    assert len(slept) == 1


def test_a_wall_ends_the_county_and_nothing_more_is_sent(monkeypatch):
    sess = install(monkeypatch, [("GET", "a.test", CLOUDFLARE_403)])
    c = nc_polite.PoliteClient("p", "NC", "Testco")
    with pytest.raises(nc_polite.RodWalled):
        c.get("https://a.test/1")
    assert nc_polite.walled_reason("p", "NC", "testco") == "HTTP 403"
    with pytest.raises(nc_polite.RodWalled):
        nc_polite.PoliteClient("p", "NC", "Testco").get("https://a.test/2")
    assert len(sess.calls) == 1                          # the second client never sent a request


def test_lookup_budget(monkeypatch):
    install(monkeypatch, [])
    monkeypatch.setenv("NC_ROD_MAX_LOOKUPS_PER_COUNTY", "2")
    assert nc_polite.take_lookup("p", "NC", "Testco")
    assert nc_polite.take_lookup("p", "NC", "Testco")
    assert not nc_polite.take_lookup("p", "NC", "Testco")
    assert nc_polite.take_lookup("p", "NC", "Otherco")
    monkeypatch.delenv("NC_ROD_MAX_LOOKUPS_PER_COUNTY")
    assert nc_polite.max_lookups_per_county() == 30


# -- the chain walk ---------------------------------------------------------------------------

def _deed(date, grantors, grantees, book, page, kind="DEED", desc=None):
    return IndexRecord(recorded=date, book=book, page=page, doc_type=kind, grantors=grantors, grantees=grantees,
                       description=desc)


class FakeIndex:
    """search(who, side, thru) over a made-up index: answers by the searched surname."""

    def __init__(self, by_last: dict[str, list[IndexRecord]], blocked: set[str] = frozenset()):
        self.by_last, self.blocked = by_last, blocked
        self.calls: list[tuple[str, str, str | None]] = []

    def __call__(self, who, side, thru):
        self.calls.append((who.last, side, thru))
        if who.last in self.blocked:
            return SearchResult(status="walled", reason="CAPTCHA")
        recs = [r for r in self.by_last.get(who.last, []) if not thru or (r.recorded or "") <= thru]
        return SearchResult(records=recs, total=len(recs))


OWNER_RECS = [
    _deed("2018-03-01", ["SAMPLE, CORA B"], ["TESTER, ALVIN Q", "TESTER, BERTHA"], "500", "10",
          desc="LOT 7 EXAMPLE ACRES"),
    _deed("2018-03-01", ["TESTER, ALVIN Q", "TESTER, BERTHA"], ["EXAMPLE BANK"], "500", "12", kind="D/T"),
    _deed("2021-06-01", ["TESTER, ALVIN Q"], ["EXAMPLE BANK"], "610", "3", kind="SAT D/T"),
    _deed("2022-02-02", ["TESTER, ALVIN Q"], ["EXAMPLE CREDIT UNION"], "640", "88", kind="DEED OF TRUST"),
    _deed("2025-11-20", ["TESTER, ALVIN Q"], ["EXAMPLE TRUSTEE SERVICES/ SUB TR"], "700", "1", kind="S/T"),
    _deed("2026-01-15", ["EXAMPLE CREDIT UNION"], ["TESTER, ALVIN Q"], "705", "40", kind="LIS PENDENS"),
    _deed("1999-01-01", ["TESTER, ALVIN Q"], ["OTHER BUYER"], "300", "5"),          # sold an earlier parcel
]
SAMPLE_RECS = [
    _deed("2001-05-05", ["DOE, DELLA"], ["SAMPLE, CORA B"], "350", "77", desc="LOT 7 EXAMPLE ACRES"),
    _deed("2019-01-01", ["SAMPLE, CORA B"], ["SOMEONE ELSE"], "520", "1"),          # after the owner's deed
]
DOE_RECS = [_deed("1980-02-02", ["EXAMPLE TRUSTEE SERVICES/ SUB TR"], ["DOE, DELLA"], "120", "9",
                  kind="TRUSTEES DEED")]


def test_chain_walks_back_and_reports_liens():
    idx = FakeIndex({"TESTER": OWNER_RECS, "SAMPLE": SAMPLE_RECS, "DOE": DOE_RECS})
    out = build_chain(platform="p", state="NC", county="Testco", owner_name="TESTER ALVIN Q", search=idx, depth=3)
    assert out["status"] == "ok"
    assert out["last_deed"]["book"] == "500" and out["last_deed"]["grantors"] == ["SAMPLE, CORA B"]
    assert out["last_deed"]["description"] == "LOT 7 EXAMPLE ACRES"
    assert [p["book"] for p in out["prior_instruments"]] == ["350", "120"]
    assert out["prior_instruments"][1]["inst_class"] == "TRUSTEE_DEED"
    assert "sale officer" in out["chain_stopped"]
    li = out["liens"]
    assert [d["book"] for d in li["deeds_of_trust"]] == ["640", "500"]
    assert [d["book"] for d in li["satisfactions"]] == ["610"]
    assert [d["book"] for d in li["substitutions_of_trustee"]] == ["700"]
    assert [d["book"] for d in li["lis_pendens"]] == ["705"]
    assert li["open_deeds_of_trust_est"] == 1 and li["since"] == "2018-03-01"
    # the grantor walk searched each grantor as grantee on or before the later deed
    assert idx.calls == [("TESTER", "both", None), ("SAMPLE", "grantee", "2018-03-01"),
                         ("DOE", "grantee", "2001-05-05")]
    assert out["searches"] == 3


def test_chain_depth_limits_the_walk():
    idx = FakeIndex({"TESTER": OWNER_RECS, "SAMPLE": SAMPLE_RECS, "DOE": DOE_RECS})
    out = build_chain(platform="p", state="NC", county="Testco", owner_name="TESTER ALVIN Q", search=idx, depth=1)
    assert len(out["prior_instruments"]) == 1 and out["chain_stopped"] is None


def test_chain_stops_honestly_when_a_grantor_search_is_walled():
    idx = FakeIndex({"TESTER": OWNER_RECS}, blocked={"SAMPLE"})
    out = build_chain(platform="p", state="NC", county="Testco", owner_name="TESTER ALVIN Q", search=idx)
    assert out["status"] == "partial" and out["reason"] == "CAPTCHA"
    assert out["last_deed"] is not None and out["prior_instruments"] == []
    assert "CAPTCHA" in out["chain_stopped"]


def test_chain_when_the_owner_search_is_walled_or_capped_or_empty():
    walled = build_chain(platform="p", state="NC", county="T", owner_name="TESTER ALVIN",
                         search=FakeIndex({}, blocked={"TESTER"}))
    assert walled["status"] == "walled" and walled["last_deed"] is None
    capped = build_chain(platform="p", state="NC", county="T", owner_name="TESTER ALVIN",
                         search=lambda w, s, t: SearchResult(status="capped", reason="cap"))
    assert capped["status"] == "capped"
    empty = build_chain(platform="p", state="NC", county="T", owner_name="TESTER ALVIN", search=FakeIndex({}))
    assert empty["status"] == "not_found" and empty["liens"]["open_deeds_of_trust_est"] == 0
    noname = build_chain(platform="p", state="NC", county="T", owner_name="", search=FakeIndex({}))
    assert noname["status"] == "no_owner_name"


def test_chain_without_a_deed_into_the_owner_is_partial():
    recs = [r for r in OWNER_RECS if r.book != "500" or r.doc_type != "DEED"]
    out = build_chain(platform="p", state="NC", county="T", owner_name="TESTER ALVIN Q",
                      search=FakeIndex({"TESTER": recs}))
    assert out["status"] == "partial" and out["last_deed"] is None
    assert out["liens"]["lis_pendens"]
