"""Offline tests for the Anderson SC register reader (rod/anderson_acpass_rod.py).

Fixtures are hand-written in the shapes ACPASS and the county parcel layer served on 2026-10-07;
every name, book and page is made up."""
from __future__ import annotations

import json

import pytest

from foreclosure_scraper.rod import anderson_acpass_rod as ac
from foreclosure_scraper.rod import sc_chain, sc_polite
from foreclosure_scraper.rod.sc_polite import PoliteSession, detect_wall


def row(key, name, role, typ, mdy, inst, book, page, desc):
    return f"""<tr><td><div align="center"><font face="Arial, Helvetica">
    <input type="checkbox" name="instryearnbr" value="{key}"> </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr={key}">{name}</a></font></td>
    <td><div align="center">{role}</div></td><td><div align="center">{typ}</div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica"> {mdy}</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">{inst}</font></div></td>
    <td><div align="center">{book}&nbsp;&nbsp;{page}</div></td></tr>
    <tr><td colspan="2"><div align="center"></div></td><td bgcolor="#003300"><font color="#FFFFFF" size="2">
    <strong>DESC:</strong></font></td><td colspan="4"><div align="left"><font size="2"><font color="#FFFFFF">
    <strong>{desc} </strong></font></font></div></td></tr>"""


def page(rows, more=None):
    more_html = ""
    if more:
        more_html = f"""<SCRIPT> function submitFunction(i) {{ if (i==3) document.theForm.action= "dednamen.cgi"; }}</SCRIPT>
        <input name="searchtype" type="hidden" value="L"> <input name="queryn" type="hidden" value="{more}">
        <input name="instrnon" type="hidden" value="L2001010000001"> <input name="seqnon" type="hidden" value="002">"""
    return f"""<html><body><form name="theForm" METHOD="POST"><table>{''.join(rows)}</table>{more_html}</form></body></html>"""


def detail(grantors, grantees):
    cells = "".join(f"<tr><td><strong>:</strong><strong>{n}</strong></td><td><strong><font>GRANTOR</font></strong></td></tr>"
                    for n in grantors)
    cells += "".join(f"<tr><td><strong>:</strong><strong>{n}</strong></td><td><strong><font>GRANTEE</font></strong></td></tr>"
                     for n in grantees)
    return f"<html><body><table>{cells}</table><a href=\"/pgms/rvimain.pgm?RQSTYP=IMAGEV\">View Images</a></body></html>"


OWNER = "WINTERBOURNE, CALLISTA R"
SELLER = "OAKHURST, DESMOND"
OWNER_PAGE = page([
    row("L2015150001111", OWNER, "GRANTEE", "DEED", "3/02/2015", "150001111", "11850", "00012", "LOT 3 HERON COVE"),
    row("L2015150001112", OWNER, "MORTGAGOR", "MORT", "3/02/2015", "150001112", "11850", "00020", "LOT 3"),
    row("L2020200002222", OWNER, "GRANTOR", "MORT SAT", "6/15/2020", "200002222", "14800", "00101", "LOT 3"),
    row("L2016160003333", "WINTERBOURNE, CALLISTA T", "GRANTEE", "DEED", "1/01/2016", "160003333", "12000", "00001", "X"),
    row("L2010100004444", "WINTERBOURNE, CEDRIC", "GRANTEE", "DEED", "1/01/2010", "100004444", "9000", "00001", "X"),
])
SELLER_PAGE = page([
    row("L2001010005555", SELLER, "GRANTEE", "DEED", "7/19/2001", "010005555", "4200", "00077", "LOT 3 HERON COVE"),
    row("L2015150001111", SELLER, "GRANTOR", "DEED", "3/02/2015", "150001111", "11850", "00012", "LOT 3"),
])


class Resp:
    def __init__(self, text, status=200, url=ac.BASE):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


class FakeHttp:
    def __init__(self, first=None, owner_page=OWNER_PAGE, gis=None):
        self.calls, self.first, self.owner_page, self.gis = [], first, owner_page, gis

    def request(self, method, url, data=None, params=None, **kw):
        self.calls.append((method, url.rsplit("/", 1)[-1], data or params))
        if "deeda.cgi" in url:
            return Resp(self.first or "<html><form action='deedmain.cgi'></form></html>")
        if url.endswith("deedmain.cgi"):
            name = data["QryName"]
            if name == "WINTERBOURNE, CALLISTA":
                return Resp(self.owner_page)
            if name == "OAKHURST, DESMOND":
                return Resp(SELLER_PAGE)
            return Resp(page([row("L1999990000001", "ZZTOP, ABE", "GRANTEE", "DEED", "1/1/1999", "1", "1", "1", "X")]))
        if "deddetail1.cgi" in url:
            if "L2015150001111" in url:
                return Resp(detail([SELLER], [OWNER, "WINTERBOURNE, AMOS"]))
            if "L2001010005555" in url:
                return Resp(detail(["HERON COVE DEVELOPMENT LLC"], [SELLER]))
            return Resp(detail([], []))
        if "FeatureServer" in url:
            assert params["outFields"] == ac.GIS_FIELDS
            return Resp(json.dumps(self.gis or {"features": []}))
        return Resp("", 404)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sc_polite.reset_walled()
    sc_polite.BUDGET.reset()
    sc_chain.clear_cache()
    monkeypatch.setattr(sc_polite, "SLEEP", lambda s: None)
    yield
    sc_polite.reset_walled()
    sc_polite.BUDGET.reset()
    sc_chain.clear_cache()


def test_parse_results_and_more():
    rows = ac.parse_results(OWNER_PAGE)
    r = rows[0]
    assert (r.name, r.role, r.doc_type, r.book, r.page, r.instrument_no) == (
        OWNER, "GRANTEE", "DEED", "11850", "12", "150001111")
    assert r.recorded.year == 2015 and r.description == "LOT 3 HERON COVE"
    assert rows[1].role == "MORTGAGOR" and rows[1].doc_type == "MORT"
    assert ac.parse_more(OWNER_PAGE) is None
    assert ac.parse_more(page([], more="WINTERBOURNE"))["queryn"] == "WINTERBOURNE"
    assert ac.parse_results("<html>no rows</html>") == []


def test_parse_detail():
    d = ac.parse_detail(detail([SELLER], [OWNER, "WINTERBOURNE, AMOS"]))
    assert d == {"GRANTOR": [SELLER], "GRANTEE": [OWNER, "WINTERBOURNE, AMOS"]}


def test_browse_term_and_past_name():
    q = sc_chain.owner_query("WINTERBOURNE CALLISTA R")
    assert ac.browse_term(q) == "WINTERBOURNE, CALLISTA"
    rows = ac.parse_results(OWNER_PAGE)
    assert ac.past_name(q, rows)                     # the page ends on WINTERBOURNE, CEDRIC
    assert not ac.past_name(q, rows[:3])


def test_chain_end_to_end_with_gap_and_parcel_flag():
    gis = {"features": [{"attributes": {"TMS": "123-45-67-890", "DBOOK": "18600", "DPAGE": "15",
                                         "SALE_YEAR": 2026, "OWNER_SSN": "000-00-0000"}}]}
    http = FakeHttp(gis=gis)
    out = ac.chain("Anderson", "WINTERBOURNE CALLISTA R", session=PoliteSession(session=http),
                   parcel_id="123-45-67-890")
    assert out["status"] == "ok" and out["platform"] == "anderson_acpass"
    ld = out["last_deed"]
    assert ld["book"] == "11850" and ld["grantors"] == [SELLER] and ld["description"] == "LOT 3 HERON COVE"
    assert out["prior_instruments"][0]["book"] == "4200"
    assert len(out["liens"]["deeds_of_trust"]) == 1 and len(out["liens"]["satisfactions"]) == 1
    assert out["index_through"] == "2026-02-20"
    assert out["after_index"]["readable_by_script"] is False
    assert out["after_index"]["newer_deed_likely"] is True
    assert "OWNER_SSN" not in json.dumps(out)
    assert any("ends 2026-02-20" in n for n in out["notes"])
    # the namesake (middle T) and the other given name are not the owner's
    assert all(i["book"] != "12000" for i in out["liens"]["deeds_of_trust"])


def test_parcel_deed_already_in_index_is_not_flagged():
    gis = {"features": [{"attributes": {"TMS": "1", "DBOOK": "11850", "DPAGE": "0012", "SALE_YEAR": 2015}}]}
    out = ac.chain("Anderson", "WINTERBOURNE CALLISTA R", session=PoliteSession(session=FakeHttp(gis=gis)),
                   parcel_id="1")
    assert "newer_deed_likely" not in out["after_index"]


def test_empty_register():
    out = ac.chain("Anderson", "NOBODY ATALL Q", session=PoliteSession(session=FakeHttp()))
    assert out["status"] == "not_found" and out["index_through"] == "2026-02-20"


def test_refused_search_is_an_error():
    http = FakeHttp(owner_page="<html>The Following Error(s) Have Been Found: Please Choose Only One Field</html>")
    out = ac.chain("Anderson", "WINTERBOURNE CALLISTA R", session=PoliteSession(session=http))
    assert out["status"] == "error"


def test_challenge_walls_the_county():
    http = FakeHttp(first="<html><title>Attention Required</title></html>")
    out = ac.chain("Anderson", "WINTERBOURNE CALLISTA R", session=PoliteSession(session=http))
    assert out["status"] == "walled"
    again = ac.chain("Anderson", SELLER, session=PoliteSession(session=http))
    assert again["status"] == "walled" and len(http.calls) == 1


def test_ingenuity_bot_check_page_is_a_wall():
    landing = """<html><head><script src="Scripts/botdetect.js"></script></head><body><form name="aspnetForm">
    <input type="hidden" name="ctl00$hdnBotResult" id="ctl00_hdnBotResult" value="" />
    <a href="javascript:__doPostBack('ctl00$ContentPlaceHolder2$btnRecording','')">Look up Land Records</a>
    </form></body></html>"""
    assert detect_wall(200, ac.INGENUITY_URL, landing) == "bot check"


def test_not_anderson():
    with pytest.raises(KeyError):
        ac.chain("Greenville", "X Y")
