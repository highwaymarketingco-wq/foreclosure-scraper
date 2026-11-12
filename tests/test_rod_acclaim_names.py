"""Offline tests for the AcclaimWeb name reader (rod/acclaim_names.py).

Fixtures are hand-written in the shapes Horry (kendo name tree, worded doc types) and Pickens
(t-treeview name tree, vendor codes) served on 2026-10-07; every name, book and page is made up."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.rod import acclaim_names as an
from foreclosure_scraper.rod import sc_chain, sc_polite
from foreclosure_scraper.rod.sc_polite import PoliteSession

BASE = "https://www.pickensscrod.us/AcclaimWeb"

DISCLAIMER = """<html><body><h2>Disclaimer</h2><form action="/AcclaimWeb/Search/Disclaimer?st=/AcclaimWeb/search/SearchTypeName"
method="post"><input id="disclaimer" name="disclaimer" type="hidden" value="true" />
<input type="submit" value="I accept the conditions above." /></form></body></html>"""

FORM = """<html><body><form action="/AcclaimWeb/search/SearchTypeName?Length=6" id="schfrm" method="post">
<input id="PartyType" name="PartyType" type="text" value="Both" />
<input id="SearchOnName" name="SearchOnName" type="text" value="" />
<input id="RecordDateFrom" name="RecordDateFrom" type="text" value="1/1/1828" />
<input id="BookTypeInfoCheckBox" name="BookTypeInfoCheckBox" type="checkbox" value="1" />
<input id="BookTypeInfoCheckBox" name="BookTypeInfoCheckBox" type="checkbox" value="2" />
<select id="DocTypeGroupDropDown" name="DocTypeGroupDropDown">
<option value="(D/EASE) DEED EASEMENT,(D/POA) POWER OF ATTORNEY,(DEED) DEED|1,2,3">DEEDS</option>
<option value="(MTG) MORTGAGE,(M/SAT) MORTGAGE SATISFACTION|4,5">MORTGAGES</option>
<option value="All|all">All</option></select></form></body></html>"""

OWNER = "ASHWORTH MIRABEL K"
SELLER = "TREMAINE BOSWELL"


def ttree(names):
    items = "".join(
        f"""<li Title="NameListTreeView_Select_{n}" class="t-item"><div class="t-top"><span class="t-checkbox">
        <input class="t-input" name="NameListTreeView_checkedNodes[0:{i}].Checked" type="checkbox" value="False" />
        </span><span class="t-in">{n} (2)</span><input class="t-input" name="itemValue" type="hidden" value="{n}" />
        </div></li>""" for i, n in enumerate(names))
    return f"""<form action="/AcclaimWeb/Search/SearchTypePreName" method="post"><input type="hidden" id="NameList" name="NameList" />
    <div class="t-widget t-treeview t-reset" id="NameListTreeView"><ul class="t-group"><li Title="NameListTreeView_SelectAll"
    class="t-item"><span class="t-in">X (9)</span><ul class="t-group">{items}</ul></li></ul></div>
    <div style="display:none;"><input name="PartyType" type="text" id="PartyType" value="Both" />
    <input name="RecordDateFrom" type="text" id="RecordDateFrom" value="1/1/1828 12:00:00 AM" />
    <input name="RecordDateTo" type="text" id="RecordDateTo" value="10/7/2026 12:00:00 AM" />
    <input name="BookTypes" type="text" id="BookTypes" value="1,2" /><input name="DocTypes" type="text" id="DocTypes" value="all" />
    <input name="SearchOnName" type="text" id="SearchOnName" value="X" /></div></form>"""


def kendo(names):
    tree = [{"id": None, "text": "TOP (9)", "expanded": True,
             "items": [{"id": None, "text": f"{n} (2)"} for n in names]}]
    return ('<div id="NameListTreeView"></div><script>kendo.syncReady(function(){jQuery("#NameListTreeView").'
            'kendoTreeView({"dataSource":' + json.dumps(tree) + ',"loadOnDemand":false});});</script>'
            '<input name="PartyType" type="text" id="PartyType" value="Reverse" />')


def row(party, name, other, code, day_ms, bp, inst, comments=""):
    return {"Party": party, "Name": name, "CrossPartyName": other, "DocType": code,
            "RecordDate": f"/Date({day_ms})/", "BookPage": bp, "InstrumentNumber": inst,
            "Comments": comments, "BookType": "DE", "TransactionId": inst}


MS_2016 = 1462147200000      # 2016-05-02
MS_2020 = 1588291200000      # 2020-05-01
MS_2005 = 1112313600000      # 2005-04-01
OWNER_ROWS = [
    row("To", OWNER, SELLER, "DEED", MS_2016, "2101/55", "201600123", "LOT 4 FOXGLOVE RIDGE"),
    row("From", OWNER, "TESTBANK OF NOWHERE NA", "MTG", MS_2016, "3001/9", "201600124"),
    row("From", OWNER, "TESTBANK OF NOWHERE NA", "M/SAT", MS_2020, "3500/1", "202000777"),
    row("To", OWNER, "UTILITY COOP", "D/EASE", MS_2020, "2500/3", "202000778"),
]
SELLER_ROWS = [row("To", SELLER, "FOXGLOVE LAND CO LLC", "DEED", MS_2005, "0950/12", "200500321", "LOT 4")]


class Resp:
    def __init__(self, text, url, status=200):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


class FakeHttp:
    def __init__(self, search_reply=None, first_page=None):
        self.calls = []
        self.term = None
        self.search_reply = search_reply
        self.first_page = first_page

    def request(self, method, url, data=None, **kw):
        self.calls.append((method, url.split("/AcclaimWeb/", 1)[-1], data))
        if url.endswith("/search/SearchTypeName") and method == "GET":
            if self.first_page is not None:
                return Resp(self.first_page, url)
            return Resp(DISCLAIMER, f"{BASE}/Search/Disclaimer?st=/AcclaimWeb/search/SearchTypeName")
        if "Disclaimer" in url:
            assert data == {"disclaimer": "true"}
            return Resp(FORM, f"{BASE}/search/SearchTypeName")
        if "SearchTypeName?Length=6" in url:
            assert data["BookTypes"] == "1,2" and data["DocTypes"] == "all"
            self.term = data["SearchOnName"]
            if self.search_reply is not None:
                return Resp(self.search_reply, url)
            if self.term == "ASHWORTH MIRABEL":
                return Resp(ttree([OWNER, "ASHWORTH MIRABEL Q"]), url)
            if self.term == "TREMAINE BOSWELL":
                assert data["PartyType"] == "Reverse"
                return Resp(kendo([SELLER]), url)
            return Resp("No names found. Please try your search again.", url)
        if "SearchTypePreName" in url:
            names = data["NameList"].split("|||")
            assert "ASHWORTH MIRABEL Q" not in names
            return Resp("<html>grid shell</html>", url)
        if "GridResults" in url:
            rows = OWNER_ROWS if self.term == "ASHWORTH MIRABEL" else SELLER_ROWS
            key = ("data", "total") if self.term == "ASHWORTH MIRABEL" else ("Data", "Total")
            return Resp(json.dumps({key[0]: rows, key[1]: len(rows)}), url)
        return Resp("", url, 404)


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


def test_parse_form():
    f = an.parse_form(FORM)
    assert f["book_types"] == ["1", "2"] and f["floor"] == "1/1/1828"
    assert f["doc_words"]["M/SAT"] == "MORTGAGE SATISFACTION" and f["doc_words"]["DEED"] == "DEED"


def test_parse_names_both_trees():
    names, hidden = an.parse_names(ttree([OWNER, SELLER]))
    assert names == [OWNER, SELLER] and hidden["BookTypes"] == "1,2" and hidden["DocTypes"] == "all"
    names, hidden = an.parse_names(kendo([OWNER]))
    assert names == [OWNER] and hidden["PartyType"] == "Reverse"
    assert an.parse_names("<html></html>") == ([], {})


def test_parse_rows_roles_and_codes():
    words = an.parse_form(FORM)["doc_words"]
    docs = an.parse_rows(OWNER_ROWS, "Pickens", words)
    deed, mtg, sat, ease = docs
    assert (deed.grantor, deed.grantee, deed.book, deed.page) == (SELLER, OWNER, "2101", "55")
    assert deed.recorded_date.year == 2016 and deed.notes == "LOT 4 FOXGLOVE RIDGE"
    assert (mtg.grantor, mtg.grantee) == (OWNER, "TESTBANK OF NOWHERE NA") and mtg.doc_type == "MORTGAGE"
    assert sat.doc_type == "MORTGAGE SATISFACTION" and sc_chain.kind_of(sat) == "satisfaction"
    assert ease.doc_type == "DEED EASEMENT" and sc_chain.kind_of(ease) == "other"


def test_parse_rows_horry_words():
    r = {"Party": "From", "Name": OWNER, "CrossPartyName": "X", "DocTypeDescription": "DEED (TIMESHARE)",
         "RecordDate": "2026/09/22", "BookPage": "5128/2855", "Consideration": 3000.0}
    d = an.parse_rows([r], "Horry")[0]
    assert d.recorded_date.isoformat().startswith("2026-09-22") and d.consideration_amount == 3000.0
    assert sc_chain.kind_of(d) == "other"


def test_check_search_reply():
    assert an.check_search_reply("No names found. Please try your search again.") == "none"
    assert an.check_search_reply(" ShowError( 'The booktype is invalid.')") == "The booktype is invalid."
    assert an.check_search_reply(ttree([OWNER])) is None


def test_chain_end_to_end():
    http = FakeHttp()
    out = an.chain("Pickens", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "ok" and out["platform"] == "harris_acclaimweb"
    assert out["last_deed"]["book"] == "2101" and out["last_deed"]["grantors"] == [SELLER]
    assert out["last_deed"]["description"] == "LOT 4 FOXGLOVE RIDGE"
    assert out["prior_instruments"][0]["book"] == "0950" and out["prior_instruments"][0]["recorded"] == "2005-04-01"
    assert len(out["liens"]["deeds_of_trust"]) == 1 and len(out["liens"]["satisfactions"]) == 1
    assert out["liens"]["open_deeds_of_trust_est"] == 0
    assert sum(1 for c in http.calls if "Disclaimer" in c[1]) == 1


def test_empty_register():
    http = FakeHttp()
    out = an.chain("Pickens", "NOBODY HERE Q", session=PoliteSession(session=http))
    assert out["status"] == "not_found"


def test_register_error_is_error_not_wall():
    http = FakeHttp(search_reply=" ShowError( 'The doctype is invalid, please try again.')")
    out = an.chain("Horry", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "error" and sc_polite.walled_reason("SC", "Horry") is None


def test_challenge_page_walls_the_county():
    http = FakeHttp(first_page="<html><head><title>Just a moment...</title></head><body>cf-chl</body></html>")
    out = an.chain("Horry", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "walled"
    again = an.chain("Horry", SELLER, session=PoliteSession(session=http))
    assert again["status"] == "walled" and len(http.calls) == 1


def test_recaptcha_widget_is_a_wall():
    page = FORM.replace("</form>", '<div class="g-recaptcha" data-sitekey="k"></div></form>')
    http = FakeHttp(first_page=page)
    out = an.chain("Pickens", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "walled" and out["reason"] == "CAPTCHA"


def test_search_by_name_unknown_county():
    assert asyncio.run(an.search_by_name("SC", "Clarendon", OWNER)) == []
