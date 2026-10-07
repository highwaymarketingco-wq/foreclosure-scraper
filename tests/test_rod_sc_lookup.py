"""Offline tests for the Spartanburg 'The Lookup' reader (rod/sc_lookup.py).

Fixtures are hand-written in the shapes the register served on 2026-10-07; every name, book and
page in them is made up."""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qsl

import pytest

from foreclosure_scraper.rod import sc_chain, sc_lookup, sc_polite
from foreclosure_scraper.rod.sc_polite import PoliteSession

BASE = "https://search.spartanburgdeeds.com"
INDEX = """<html><head><title>Spartanburg County Register of Deeds - Property Search</title></head><body>
<form method="post" target="content_frame" action="content.php?1234567" id="name_form"></form></body></html>"""


def pick(names):
    rows = "".join(
        f"""<tr><td><input type="checkbox" name="name[]" value="{n}" id="pl_{n.replace(' ', '_')}_"
        aria-label="{n}" onclick="storeEID({c}, '{n.replace(' ', '_')}')"/> &nbsp;</td>
        <td><label>{n}</label>&nbsp;</td><td>{c}&nbsp; </td></tr>""" for n, c in names)
    return f"""<html><body><form method="post" action="content.php" name="pickListForm" id="pickListForm">
    <input type="hidden" name="searchType" value="name"/><input type="hidden" name="start_date" value="" id="start_date">
    <input type="hidden" name="end_date" value="" id="end_date"><input type="hidden" name="last_name" value="X" id="last_name">
    <input type="hidden" name="party_type" value="Both" id="party_type">
    <table id="plresults"><tbody>{rows}</tbody></table></form></body></html>"""


def rec_row(inst, mdy, book_info, typ, desc, role, searched, reverse):
    br = lambda names: "".join(f"{n} <br> " for n in names)  # noqa: E731
    return f"""<tr id="{inst}"><td><font class="invisibleText">x</font>
    <a href="javascript: loadDetailsScreen('{inst}');" id="link_{inst}"> {mdy}&nbsp;</a></td>
    <td class="summary" id="{inst}"> {book_info} &nbsp; </td><td class="summary" id="{inst}">{typ}&nbsp;</td>
    <td class="summary" id="{inst}"> {desc}<br> &nbsp; </td><td class="summary" id="{inst}"> {role}&nbsp;</td>
    <td class="summary" id="{inst}"> {br(searched)}&nbsp; </td><td class="summary" id="{inst}"> {br(reverse)}</td>
    <td><a href="view_image.php?key=abc">View Image</a></td></tr>"""


OWNER = "FERNSBY ORLA K"
SELLER = "MARCHETTI DOV"
OWNER_RECORDS = "<html><body><table>" + "".join([
    rec_row("2019004567", "05/06/2019", "DEE 120-K 45", "DEED", "LOT 8 PINE KNOLL", "Party 2",
            [OWNER, "FERNSBY ABEL"], [SELLER]),
    rec_row("2019004568", "05/06/2019", "MTG 5500 12", "MORTGAGE", "LOT 8", "Party 1",
            [OWNER, "FERNSBY ABEL"], ["TESTBANK OF NOWHERE NA"]),
    rec_row("2021000099", "02/02/2021", "LIE 30 1", "LIEN", "JUDGMENT", "Party 2", [OWNER], ["SOMECO LLC"]),
]) + "</table></body></html>"
SELLER_RECORDS = "<html><body><table>" + rec_row(
    "2008001111", "11/20/2008", "DEE 95-B 300", "DEED", "LOT 8 PINE KNOLL", "Party 2", [SELLER],
    ["PINE KNOLL HOMES LLC"]) + "</table></body></html>"


class Resp:
    def __init__(self, text, status=200, url=BASE):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


class FakeHttp:
    def __init__(self, index=INDEX, hold=None):
        self.index, self.hold = index, hold
        self.calls, self.held, self.last = [], [], None

    def request(self, method, url, data=None, params=None, **kw):
        self.calls.append((method, url.rsplit("/", 1)[-1], data or params))
        if "index.php" in url:
            return Resp(self.index)
        if url.endswith("content.php") and params:
            self.held, self.last = [], (params["last_name"], params["first_name"])
            if self.last == ("FERNSBY", "ORLA"):
                return Resp(pick([(OWNER, 3), ("FERNSBY ORLA T", 2)]))
            if self.last == ("MARCHETTI", "DOV"):
                assert params["party_type"] == "Grantee" and params["end_date"] == "05/06/2019"
                return Resp(pick([(SELLER, 1)]))
            return Resp(pick([]))
        if url.endswith("ajaxActions.php"):
            if data["action"] == "storeEID":
                self.held.append(data["entityID"])
                return Resp("")
            if data["action"] == "checkEID":
                return Resp(str(self.hold if self.hold is not None else len(self.held)))
            if data["action"] == "storeDataString":
                names = [v for k, v in parse_qsl(data["dataString"]) if k == "name[]"]
                assert "FERNSBY ORLA T" not in names
                return Resp("")
        if "content.php?embedded=1" in url:
            return Resp(OWNER_RECORDS if self.last == ("FERNSBY", "ORLA") else SELLER_RECORDS)
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


def test_parse_pick():
    boxes, hidden = sc_lookup.parse_pick(pick([(OWNER, 3)]))
    assert [(b.value, b.count, b.eid) for b in boxes] == [(OWNER, 3, "FERNSBY_ORLA_K")]
    assert ("party_type", "Both") in hidden
    assert sc_lookup.parse_pick(pick([])) == ([], hidden)


def test_to_docs_sides_and_br_names():
    docs = sc_lookup.to_docs(OWNER_RECORDS, "Spartanburg")
    deed, mtg, lien = docs
    assert (deed.book, deed.page, deed.doc_type) == ("120-K", "45", "DEED")
    assert deed.grantor == SELLER and deed.grantee == f"{OWNER}; FERNSBY ABEL"     # Party 2 = grantee side
    assert mtg.grantor == f"{OWNER}; FERNSBY ABEL" and mtg.grantee == "TESTBANK OF NOWHERE NA"
    assert deed.recorded_date.year == 2019 and deed.notes == "LOT 8 PINE KNOLL"
    assert sc_chain.kind_of(lien) == "lien"


def test_chain_end_to_end():
    http = FakeHttp()
    out = sc_lookup.chain("Spartanburg", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "ok" and out["platform"] == "sc_logan_lookup"
    assert out["last_deed"]["book"] == "120-K" and out["last_deed"]["grantors"] == [SELLER]
    assert out["prior_instruments"][0]["book"] == "95-B"
    assert len(out["liens"]["deeds_of_trust"]) == 1 and len(out["liens"]["other_liens"]) == 1


def test_session_holding_the_wrong_names_is_an_error():
    out = sc_lookup.chain("Spartanburg", OWNER, session=PoliteSession(session=FakeHttp(hold=5)))
    assert out["status"] == "error" and "session holds" in out["reason"]


def test_empty_pick_list():
    out = sc_lookup.chain("Spartanburg", "NOBODY HERE Q", session=PoliteSession(session=FakeHttp()))
    assert out["status"] == "not_found"


def test_error_page():
    out = sc_lookup.chain("Spartanburg", OWNER, session=PoliteSession(session=FakeHttp(index="<html>Down</html>")))
    assert out["status"] == "error"


def test_challenge_walls_and_stops():
    http = FakeHttp(index="<html><head><title>Just a moment...</title></head></html>")
    out = sc_lookup.chain("Spartanburg", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "walled"
    assert sc_lookup.chain("Spartanburg", SELLER, session=PoliteSession(session=http))["status"] == "walled"
    assert len(http.calls) == 1


def test_unknown_county():
    assert asyncio.run(sc_lookup.search_by_name("SC", "Greenwood", OWNER)) == []
