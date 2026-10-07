"""Offline tests for the Union SC (Cott RecordRoom, rod/sc_recordroom.py) and Marlboro SC (older
Cott eSearch, rod/sc_cott_esearch.py) name readers. Hand-written fixtures in the shapes the
registers served on 2026-10-07; every name, book and page is made up."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.rod import sc_chain, sc_cott_esearch as ce, sc_polite, sc_recordroom as rr
from foreclosure_scraper.rod.sc_polite import PoliteSession


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


class Resp:
    def __init__(self, text, status=200, url="https://example.test/"):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


OWNER = "OSTRANDER FENELLA J"
SELLER = "PRICKETT SILAS"

# ------------------------------------------------------------------ Union (RecordRoom) -------
def rr_row(day, typ, p1, p2, bp, remarks="", amount=None, addr=False):
    def cell(names):
        inner = "".join(f"<div>{n}</div>" for n in names)
        if addr:
            inner += ('<div class="indexdetail_address"><span class="indexdetail_label">Address: </span>'
                      '<span class="indexdetail_data">1 TEST LANE, NOWHERE SC 29000</span></div>')
        return inner
    prop = (f'<span class="amtDesc"> <strong>Amount:</strong> ${amount:,.2f}</span>' if amount else "") + \
        ('<div><div data-propertyid="1"><div class="indexdetail_primary"><strong>Parcel #:</strong> '
         '<span class="indexdetail_data"><a class="gpinActive" href="#">000-00-00-000.000</a></span> '
         f'<strong>Remarks:</strong> <span class="indexdetail_data">{remarks}</span></div></div></div>')
    return {"TotalRecords": 1, "IndexId": 1, "ScanPages": 2, "RecordingDate": day, "Type": typ,
            "PartyOne": cell(p1), "PartyTwo": cell(p2), "Property": prop, "FileNumber": "",
            "BookPage": bp, "HasRelatedDocument": 0, "HasFiledImage": 1, "IsCorrected": False}


RR_OWNER = [rr_row("05/01/2018", "DEE<br/>DEED", [SELLER], ["OSTRANDER, FENELLA J"], "  300 /   12",
                   "LOT 4 WREN HOLLOW", 120000.0, addr=True),
            rr_row("05/01/2018", "MTG<br/>MTG", ["OSTRANDER, FENELLA J"], ["TESTBANK OF NOWHERE NA"], "  410 /   7")]
RR_SELLER = [rr_row("02/02/2001", "DEE<br/>DEED", ["WREN HOLLOW LAND CO"], [SELLER], "  100 /   55", "LOT 4")]


class FakeRR:
    def __init__(self, first="<html>search</html>"):
        self.first, self.calls, self.term = first, [], None

    def request(self, method, url, data=None, json=None, **kw):
        self.calls.append((method, url.rsplit("/unionsc", 1)[-1]))
        if url.endswith("/guest/Search/records"):
            return Resp(self.first, url=url)
        if url.endswith("/search/Records"):
            self.term = dict(data)["SearchTerm"]
            return Resp("<html>result shell</html>", url=url.replace("/search/Records", "/Guest/Search/Records/Result"))
        if "SelectedSearch" in url:
            return Resp('{"UnparsedNameSearch": true}')
        if url.endswith("/Search/Records/Result/"):
            import json as _j
            rows = RR_OWNER if self.term == "OSTRANDER FENELLA" else RR_SELLER if self.term == "PRICKETT SILAS" else None
            if rows is None:
                return Resp(_j.dumps({"draw": "1", "recordsTotal": 0, "recordsFiltered": 0, "data": {}}))
            return Resp(_j.dumps({"draw": "1", "recordsTotal": len(rows), "recordsFiltered": len(rows), "data": rows}))
        return Resp("", 404)


def test_union_parse_rows():
    d, m = rr.parse_rows(RR_OWNER, "Union")
    assert (d.doc_type, d.book, d.page, d.grantor, d.grantee) == ("DEED", "300", "12", SELLER, "OSTRANDER, FENELLA J")
    assert d.notes == "LOT 4 WREN HOLLOW" and d.amount == 120000.0 and d.parcel_id == "000-00-00-000.000"
    assert m.doc_type == "MTG" and sc_chain.kind_of(m) == "mortgage"
    assert rr.party_names(RR_OWNER[0]["PartyTwo"]) == ["OSTRANDER, FENELLA J"]        # address dropped


def test_union_form_uses_the_quick_name_box():
    form = dict(rr.search_form("OSTRANDER FENELLA", "grantee", None, None))
    assert form["SearchTerm"] == "OSTRANDER FENELLA" and form["PartyType"] == "9" and form["Type"] == "0"
    assert form["Names[0].LastName"] == ""


def test_union_chain():
    http = FakeRR()
    out = rr.chain("Union", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "ok" and out["last_deed"]["book"] == "300"
    assert out["prior_instruments"][0]["book"] == "100"
    assert len(out["liens"]["deeds_of_trust"]) == 1


def test_union_empty_and_wall():
    assert rr.chain("Union", "NOBODY ATALL Q", session=PoliteSession(session=FakeRR()))["status"] == "not_found"
    http = FakeRR(first="<title>Just a moment...</title>")
    assert rr.chain("Union", OWNER, session=PoliteSession(session=http))["status"] == "walled"
    assert rr.chain("Union", SELLER, session=PoliteSession(session=http))["status"] == "walled"
    assert len(http.calls) == 1


# ------------------------------------------------------------ Marlboro (older eSearch) -------
FORM = ('<html><form><input type="hidden" name="ctl00_smScriptMan_HiddenField" id="ctl00_smScriptMan_HiddenField" '
        'value=";;Toolkit:abc" /><input name="ctl00$cphMain$SrchNames1$txtFirmSurName" type="text" /></form></html>')


def ce_row(i, idx, day, typ, p1, p2, desc, bp):
    def names(ns, bold):
        return "".join(f"<tr><td colspan='2'>{'<b>' + n + '</b>' if bold else n}</td></tr>" for n in ns) or \
            "<tr><td colspan='2'>-----</td></tr>"
    return (f"<tr class='GridView_Row'><td>{i}</td><td><input type='checkbox' /></td><td>{idx}</td>"
            f"<td>{day}<br><span class='StatusDate'><br>01/01/9998</span></td><td style='font-weight:bold;'>{typ}</td>"
            f"<td><div title='Collapsed'><table><tbody>{names(p1, True)}</tbody></table></div></td>"
            f"<td><div title='Collapsed'><table><tbody>{names(p2, False)}</tbody></table></div></td>"
            f"<td><div title='Collapsed'><table><tbody><tr><td colspan='2'>{desc}</td></tr></tbody></table></div></td>"
            f"<td><a href='#'></a></td><td><a href='#'>  {bp}</a></td><td><div></div></td><td><a></a></td><td><a>Flag</a></td></tr>")


def grid(rows):
    return (f"<html><span>Displaying records 1 - {len(rows)} of {len(rows)} at 5:24 PM ET</span>"
            f"<table id='{ce.GRID_ID}' class='GridView'><tbody><tr><th>Select</th></tr>{''.join(rows)}</tbody></table></html>")


CE_OWNER = grid([ce_row(1, "LAN", "05/01/2018", "DEED", [SELLER], ["OSTRANDER FENELLA J"], "[] LOT 4 WREN HOLLOW", "300 / 12"),
                 ce_row(2, "LAN", "05/01/2018", "&nbsp;", ["OSTRANDER FENELLA J"], ["TESTBANK OF NOWHERE NA"],
                        "LOT 4 [MTG]", "410 / 7")])
CE_SELLER = grid([ce_row(1, "LAN", "02/02/2001", "DEED", ["WREN HOLLOW LAND CO"], [SELLER], "LOT 4", "100 / 55")])
NONE = "<html><span>Your search did not return any results at 5:26 PM ET. Please modify your search criteria.</span></html>"


class FakeCE:
    def __init__(self, first=FORM, blank=False):
        self.first, self.blank, self.calls = first, blank, []

    def request(self, method, url, data=None, **kw):
        self.calls.append(method)
        if method == "GET":
            return Resp(self.first, url=url)
        d = dict(data)
        assert d["ctl00_smScriptMan_HiddenField"] == ";;Toolkit:abc" and d["hiddenInputToUpdateATBuffer_CommonToolkitScripts"] == "1"
        if self.blank:
            return Resp(FORM)
        last = d["ctl00$cphMain$SrchNames1$txtFirmSurName"]
        if last == "OSTRANDER":
            return Resp(CE_OWNER)
        if last == "PRICKETT":
            assert d["ctl00$cphMain$SrchNames1$ddlParty"] == "2" and d["ctl00$cphMain$SrchDates1$txtFiledThru"] == "05/01/2018"
            return Resp(CE_SELLER)
        return Resp(NONE)


def test_marlboro_parse_grid():
    docs, total = ce.parse_grid(CE_OWNER, "Marlboro")
    deed, mtg = docs
    assert total == 2 and (deed.book, deed.page, deed.grantor, deed.grantee) == ("300", "12", SELLER, "OSTRANDER FENELLA J")
    assert deed.notes == "LOT 4 WREN HOLLOW"
    assert mtg.doc_type == "MORTGAGE" and mtg.notes == "LOT 4"          # [MTG] tag when Doc Type is empty
    assert ce.parse_grid(NONE, "Marlboro") == ([], None)


def test_marlboro_chain():
    out = ce.chain("Marlboro", OWNER, session=PoliteSession(session=FakeCE()))
    assert out["status"] == "ok" and out["last_deed"]["book"] == "300"
    assert out["prior_instruments"][0]["book"] == "100" and len(out["liens"]["deeds_of_trust"]) == 1


def test_marlboro_no_results_and_blank_form():
    assert ce.chain("Marlboro", "NOBODY ATALL Q", session=PoliteSession(session=FakeCE()))["status"] == "not_found"
    assert ce.chain("Marlboro", OWNER, session=PoliteSession(session=FakeCE(blank=True)))["status"] == "error"


def test_marlboro_login_page_is_a_wall():
    login = '<html><form action="Login.aspx"><input type="password" name="pw" /></form></html>'

    class LoginHttp(FakeCE):
        def request(self, method, url, data=None, **kw):
            self.calls.append(method)
            return Resp(login, url="http://www.cotthosting.com/scmarlboro/User/Login.aspx?ReturnUrl=x")
    http = LoginHttp()
    out = ce.chain("Marlboro", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "walled" and out["reason"] == "login page"
    assert ce.chain("Marlboro", SELLER, session=PoliteSession(session=http))["status"] == "walled"
    assert http.calls == ["GET"]


def test_other_counties():
    assert asyncio.run(rr.search_by_name("SC", "Laurens", OWNER)) == []
    assert asyncio.run(ce.search_by_name("SC", "Laurens", OWNER)) == []
