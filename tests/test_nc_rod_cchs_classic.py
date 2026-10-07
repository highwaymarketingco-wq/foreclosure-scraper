"""CCHS classic adapter for the county-hosted tenants (rod/nc_cchs_classic.py) on hand-written
replies shaped like SearchService.asp's XML (made-up names, books, pages; no fetched content).
Covers the parse (party rows folded per document, CDATA, entities), the request sequence, an empty
answer, an error reply, a Cloudflare challenge and a CAPTCHA on the bootstrap (walled, never
retried), and chain()."""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from foreclosure_scraper.rod import nc_cchs_classic as cc
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, SERVER_ERROR, FakeResp, install

APP_PAGE = "<html><body><frameset><frame src='realestatesearch.asp'/></frameset></body></html>"
SEARCH_PAGE = ("<html><body><form name='myForm'><input type='radio' name='searchtype' value='3' checked/></form>"
               "<script>this.lastURL = \"SearchService.asp?cmd=search&\" + qs</script></body></html>")


def reply(n, d):
    return f"<SearchResponse><recordcount>{n}</recordcount><primarySortField>DATE</primarySortField><doccount>{d}</doccount></SearchResponse>"


def r(da, ki, bk, pg, dn, gl, gf, el, ef, de=""):
    return (f"<r><da>{da}</da><ki><![CDATA[{ki}]]></ki><bk>{bk}</bk><pg>{pg}</pg><dn>{dn}</dn><or>{gl}</or>"
            f"<or1>{gf}</or1><orc>I</orc><ee>{el}</ee><ee1>{ef}</ee1><eec>F</eec><de><![CDATA[{de}]]></de>"
            "<pk>0000-00-0000</pk></r>")


GETALL_TESTER = "<Records>" + "".join([
    r("01/15/2026", "LIS P", "700", "40", "2026000300", "EXAMPLE BANK", "", "TESTER", "ALVIN Q"),
    r("02/02/2022", "D/T", "640", "88", "2022000200", "TESTER", "ALVIN Q", "EXAMPLE BANK", ""),
    r("02/02/2022", "D/T", "640", "88", "2022000200", "TESTER", "BERTHA", "EXAMPLE BANK", ""),
    r("06/01/2021", "SATIS", "610", "3", "2021000150", "TESTER", "ALVIN Q", "EXAMPLE BANK", "", "500/12"),
    r("03/01/2018", "DEED", "500", "10", "2018000100", "SAMPLE", "CORA B", "TESTER", "ALVIN Q",
      "LOT: 7 SUB: EXAMPLE ACRES &amp; ANNEX"),
]) + "</Records>"
GETALL_SAMPLE = "<Records>" + r("05/05/2001", "DEED", "350", "77", "2001000050", "DOE", "DELLA", "SAMPLE", "CORA B",
                                "LOT: 7 SUB: EXAMPLE ACRES") + "</Records>"


class Site:
    def __init__(self):
        self.last = ""

    def routes(self):
        return [("GET", "application.asp", FakeResp(APP_PAGE)), ("GET", "realestatesearch.asp", FakeResp(SEARCH_PAGE)),
                ("GET", "SearchService.asp", self.service)]

    def service(self, method, url, params, data):
        q = parse_qs(urlsplit(url).query)
        if q["cmd"][0] == "search":
            self.last = q["last"][0]
            return FakeResp({"TESTER": reply(5, 4), "SAMPLE": reply(1, 1)}.get(self.last, reply(0, 0)))
        return FakeResp({"TESTER": GETALL_TESTER, "SAMPLE": GETALL_SAMPLE}.get(self.last, "<Records></Records>"))


@pytest.fixture
def fake(monkeypatch):
    def go(routes):
        return install(monkeypatch, routes, cc.ADAPTER)
    yield go
    cc.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_counts_and_parse_getall():
    assert cc.counts(reply(16, 6)) == (16, 6)
    assert cc.counts("<html>error</html>") == (None, None)
    recs = cc.parse_getall(GETALL_TESTER)
    assert [x.book for x in recs] == ["700", "640", "610", "500"]
    lp, dt, sat, deed = recs
    assert (lp.kind, lp.grantors, lp.grantees, lp.recorded) == ("lis_pendens", ["EXAMPLE BANK"], ["TESTER ALVIN Q"],
                                                                "2026-01-15")
    assert (dt.kind, dt.grantors, dt.instrument_no) == ("deed_of_trust", ["TESTER ALVIN Q", "TESTER BERTHA"], "2022000200")
    assert (sat.kind, sat.description) == ("satisfaction", "500/12")
    assert deed.description == "LOT: 7 SUB: EXAMPLE ACRES & ANNEX"


def test_search_query_sides_and_dates():
    q = cc.search_query(OwnerName(raw="x", last="TESTER", first="ALVIN"), "grantee", "2018-03-01")
    assert (q["last"], q["given"], q["searchtype"], q["todate"], q["indextype"], q["codetype"]) == \
        ("TESTER", "ALVIN", "2", "03/01/2018", "3", "3")
    q = cc.search_query(OwnerName(raw="x", last="EXAMPLE HOLDINGS LLC", entity=True), "both", None)
    assert q["given"] == "" and q["searchtype"] == "3" and q["todate"] == ""


def test_sequence_and_chain(fake):
    sess = fake(Site().routes())
    out = cc.chain("Orange", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]
    assert [d["book"] for d in out["liens"]["lis_pendens"]] == ["700"]
    assert out["liens"]["open_deeds_of_trust_est"] == 0
    paths = [urlsplit(c[1]).path.rsplit("/", 1)[-1] for c in sess.calls]
    assert paths[:5] == ["", "application.asp", "realestatesearch.asp", "SearchService.asp", "SearchService.asp"]
    assert sess.calls[0][1] == "https://rod.orangecountync.gov/orangenc/"
    assert "cmd=getall&start=0&offset=5" in sess.calls[4][1]


def test_search_by_name(fake):
    fake(Site().routes())
    docs = asyncio.run(cc.search_by_name("NC", "Surry", "TESTER ALVIN Q"))
    assert len(docs) == 4 and docs[1].grantor == "TESTER ALVIN Q; TESTER BERTHA"
    assert asyncio.run(cc.search_by_name("NC", "Gates", "TESTER ALVIN Q")) == []      # hosted: walled, not configured


def test_empty_answer(fake):
    sess = fake(Site().routes())
    res = cc.ADAPTER.search("Orange", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0
    assert not any("getall" in c[1] for c in sess.calls)


def test_error_reply(fake):
    fake([("GET", "application.asp", FakeResp(APP_PAGE)), ("GET", "realestatesearch.asp", FakeResp(SEARCH_PAGE)),
          ("GET", "SearchService.asp", SERVER_ERROR)])
    res = cc.ADAPTER.search("Orange", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and res.reason == "HTTP 500"
    fake([("GET", "application.asp", FakeResp(APP_PAGE)), ("GET", "realestatesearch.asp", FakeResp(SEARCH_PAGE)),
          ("GET", "SearchService.asp", FakeResp("<html>An error occurred</html>"))])
    res = cc.ADAPTER.search("Orange", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "record count" in res.reason


@pytest.mark.parametrize("wall,reason", [(CLOUDFLARE_403, "HTTP 403"), (CAPTCHA_PAGE, "CAPTCHA")])
def test_blocked_bootstrap_is_walled_and_never_retried(fake, wall, reason):
    sess = fake([("GET", "application.asp", wall)])
    res = cc.ADAPTER.search("Stanly", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(cc.search_by_name("NC", "Stanly", "SAMPLE CORA")) == []
    assert cc.chain("Stanly", "TESTER ALVIN Q")["status"] == "walled"
    assert len(sess.calls) == 1                       # Stanly has no root page: application.asp is the first


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    for county in cc.COUNTIES:
        assert g.ROD_CONFIG[("NC", county)] == ("nc_cchs_classic", cc.ENV_FLAG, "0")
    for county in cc.HOSTED_WALLED:
        assert ("NC", county) not in g.ROD_CONFIG
