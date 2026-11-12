"""Offline tests for the SC 'Online Record System' reader (rod/sc_online_record_system.py).

Fixtures are hand-written in the page shapes the live registers served on 2026-10-07 (Laurens,
Lancaster, Georgetown, Barnwell); every name, book and page in them is made up."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from foreclosure_scraper.rod import sc_chain, sc_polite
from foreclosure_scraper.rod import sc_online_record_system as ors
from foreclosure_scraper.rod.sc_polite import PoliteSession

SEARCH_PAGE = """<html><body><form method="post" action="NamePick.php" id="frmlookup_form"
name="frmlookup_form"><input type="radio" name="search_type" value="Standard">
<input type="text" name="tor_last_name"><input type="checkbox" name="search_each">
<input type="text" name="tee_last_name"></form>""" + "<!-- pad -->" * 10 + "</body></html>"

DISCLAIMER = """<html><body><form method="post" action="NameSearch.php"><p>The information is provided
as is.</p><input type="submit" name="Accept" value="Accept"></form></body></html>"""


def pick_page(names: list[tuple[str, int]]) -> str:
    rows = "".join(
        f"""<tr bgcolor='#FFFFFF'><td headers="rowselector" align='center'>
        <input type = 'checkbox' value = '{n.replace(' ', '')}' name = 'entityID[{n.replace(' ', '')}]'
        id='?{n.replace(' ', '')}' aria-label='{n}'></td>
        <td headers="nameheader">{n}</td><td headers="countheader"> {c} &nbsp;</td></tr>"""
        for n, c in names)
    return f"""<html><body><script>const searchLimit = 2000;</script>
    <form name="frm" method="post" action="NameDisplay.php">
    <input type="hidden" name="igheader" value="ALL"><input type="hidden" name="igquerystring" value="">
    <table><tr><th id="nameheader">Grantor/ Grantee Last or Company name</th><th id="countheader">Count</th></tr>
    {rows}</table></form></body></html>"""


def sortable_row(day_iso, mdy, bp, typ, grantor, grantee, role, desc, amount="", inst="2020001234"):
    return (f'<tr><td data-order="{day_iso}"><a href="DetailScreen.php?inst_num={inst}">{mdy}</a></td>'
            f"<td>{bp}</td><td>{typ}</td><td>{grantor}</td><td>{grantee}</td><td>{role}</td>"
            f"<td>{desc}</td><td>{amount}</td><td><a href=\"view_image.php?file=x&type=pdf\">PDF</a></td></tr>")


def display_sortable(rows: list[str]) -> str:
    return ("""<html><body><table><tbody id="grouped-rows"><tr><td colspan=8>group view</td></tr></tbody></table>
    <div id="sortable-view"><table id="sortableResultsTable" class="display"><thead><tr><th>Date</th>
    <th>Book-Page</th><th>Type</th><th>Grantor</th><th>Grantee</th><th>Party&nbsp;Type</th><th>Description</th>
    <th>Amount</th><th>Image</th></tr></thead><tbody>""" + "".join(rows) + "</tbody></table></div></body></html>")


DISPLAY_GROUPED = """<html><body><table>
<tr><td colspan=8 bgcolor='#CCCCCC'><b>PENROSE WILHELMINA J ( Grantee) </b></td></tr>
<tr><td width='10%'><b>Date</td><td><b>Code-Book-Page</td><td><b>Type</td><td><b>Description</td>
<td><b>Amount</td><td><b>One Reverse Party / D Status</td><td><b>Cross-Ref</td><td><b>Img?</td></tr>
<tr bgcolor="#FFFFFF"><td><a href="DetailScreen.php?inst_num=2017004321">06/02/2017</a></td>
<td>DEED BOOK-1501-77</td><td>DEED</td><td>PD:LOT 9 BRIAR GLEN</td><td></td><td>HOLLOWAY CEDRIC &nbsp;</td>
<td>&nbsp;</td><td>PDF</td></tr>
<tr><td colspan=8 bgcolor='#CCCCCC'><b>PENROSE WILHELMINA J ( Grantor) </b></td></tr>
<tr><td><b>Date</td><td><b>Code-Book-Page</td><td><b>Type</td><td><b>Description</td><td><b>Amount</td>
<td><b>One Reverse Party / D Status</td><td><b>Cross-Ref</td><td><b>Img?</td></tr>
<tr bgcolor="#FFFFFF"><td><a href="DetailScreen.php?inst_num=2017004322">06/02/2017</a></td>
<td>MORTGAGE BOOK-3300-12</td><td>MORTGAGE</td><td>PD:LOT 9</td><td>150000.00</td>
<td>TESTBANK OF NOWHERE NA</td><td></td><td>PDF</td></tr>
</table></body></html>"""

OWNER = "PENROSE WILHELMINA J"
SELLER = "HOLLOWAY CEDRIC"
OWNER_ROWS = [
    sortable_row("2017-06-02", "06/02/2017", "DEED BOOK-1501-77", "DEED", SELLER, OWNER, "Grantee",
                 "PD:LOT 9 BRIAR GLEN"),
    sortable_row("2017-06-02", "06/02/2017", "MORTGAGE BOOK-3300-12", "MORTGAGE", OWNER, "TESTBANK OF NOWHERE NA",
                 "Grantor", "PD:LOT 9", "150000.00"),
    sortable_row("2023-02-14", "02/14/2023", "MORTGAGE BOOK-4100-5", "SATISFACTION MORTGAGE", OWNER,
                 "TESTBANK OF NOWHERE NA", "Grantor", ""),
    sortable_row("2025-11-03", "11/03/2025", "LIS PENDENS-88-14", "LIS PENDENS", "SECOND TESTBANK", OWNER,
                 "Grantee", "PD:LOT 9"),
]
SELLER_ROWS = [
    sortable_row("2004-03-30", "03/30/2004", "DEED BOOK-0790-0402", "DEED", "BRIAR GLEN DEVELOPERS LLC", SELLER,
                 "Grantee", "PD:LOT 9 BRIAR GLEN"),
    sortable_row("2019-01-01", "01/01/2019", "DEED BOOK-1700-1", "DEED", "LATER SELLER", SELLER, "Grantee", ""),
]


class Resp:
    def __init__(self, text, status=200, url="https://search.laurensdeeds.com/x"):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}


class FakeHttp:
    """Routes NameSearch / NamePick / NameDisplay to canned pages by the searched name."""

    def __init__(self, search_page=SEARCH_PAGE, pick_status=200):
        self.search_page, self.pick_status = search_page, pick_status
        self.calls: list[tuple[str, str, dict]] = []
        self.last_name = ""

    def request(self, method, url, data=None, **kw):
        self.calls.append((method, url.rsplit("/", 1)[-1], data))
        if "NameSearch.php" in url:
            return Resp(self.search_page)
        if "NamePick.php" in url:
            if self.pick_status != 200:
                return Resp("<html>Internal Server Error</html>", self.pick_status)
            self.last_name = data.get("tor_last_name") or data.get("tee_last_name")
            if self.last_name == "PENROSE WILHELMINA":
                return Resp(pick_page([(OWNER, 4), ("PENROSE WILHELMINA T", 2), ("PENROSE WALTER", 1)]))
            if self.last_name == "HOLLOWAY CEDRIC":
                return Resp(pick_page([(SELLER, 2)]))
            return Resp(pick_page([]))
        if "NameDisplay.php" in url:
            ticked = [v for k, v in data if k.startswith("entityID[")]
            if self.last_name == "PENROSE WILHELMINA":
                assert ticked == ["PENROSEWILHELMINAJ"]          # the middle-T namesake is not ticked
                return Resp(display_sortable(OWNER_ROWS))
            if self.last_name == "HOLLOWAY CEDRIC":
                return Resp(display_sortable(SELLER_ROWS))
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
    picks = ors.parse_pick(pick_page([(OWNER, 4), ("PENROSE WALTER", 1)]))
    assert [(p.entity_id, p.name, p.count) for p in picks] == [
        ("PENROSEWILHELMINAJ", OWNER, 4), ("PENROSEWALTER", "PENROSE WALTER", 1)]
    assert ors.parse_pick(pick_page([])) == []


def test_split_book_page():
    assert ors.split_book_page("RECORD BOOK-5077-480") == ("RECORD BOOK", "5077", "480")
    assert ors.split_book_page("DEED-2113-253") == ("DEED", "2113", "253")
    assert ors.split_book_page("DEED BOOK-0790-0402") == ("DEED BOOK", "790", "402")
    assert ors.split_book_page("no book") == (None, None, None)


def test_parse_display_sortable():
    docs = ors.parse_display(display_sortable(OWNER_ROWS), "Laurens")
    assert len(docs) == 4
    d = docs[0]
    assert (d.book, d.page, d.doc_type, d.grantor, d.grantee) == ("1501", "77", "DEED", SELLER, OWNER)
    assert d.recorded_date.year == 2017 and d.instrument_no == "2020001234"
    assert d.notes == "PD:LOT 9 BRIAR GLEN" and d.raw["party_role"] == "Grantee"
    assert docs[1].amount == 150000.0


def test_parse_display_grouped_fallback():
    docs = ors.parse_display(DISPLAY_GROUPED, "Georgetown")
    assert [(d.doc_type, d.grantor, d.grantee) for d in docs] == [
        ("DEED", "HOLLOWAY CEDRIC", OWNER), ("MORTGAGE", OWNER, "TESTBANK OF NOWHERE NA")]
    assert docs[0].book == "1501" and docs[0].instrument_no == "2017004321"


def test_parse_display_empty():
    assert ors.parse_display(display_sortable([]), "Laurens") == []
    assert ors.parse_display("<html><body>No records</body></html>", "Laurens") == []


def test_chain_end_to_end():
    http = FakeHttp()
    out = ors.chain("Laurens", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "ok" and out["platform"] == "sc_online_record_system"
    assert out["last_deed"]["book"] == "1501" and out["last_deed"]["grantors"] == [SELLER]
    assert out["prior_instruments"][0]["book"] == "790" and out["prior_instruments"][0]["recorded"] == "2004-03-30"
    liens = out["liens"]
    assert len(liens["deeds_of_trust"]) == 1 and len(liens["satisfactions"]) == 1
    assert liens["lis_pendens"][0]["type"] == "LIS PENDENS" and liens["open_deeds_of_trust_est"] == 0
    picks = [c[2] for c in http.calls if c[1] == "NamePick.php"]
    assert picks[0]["search_each"] == "on" and picks[0]["tor_last_name"] == "PENROSE WILHELMINA"
    assert picks[1]["tee_last_name"] == "HOLLOWAY CEDRIC" and picks[1]["end_date"] == "06/02/2017"
    assert sum(1 for c in http.calls if c[1].startswith("NameSearch.php")) == 1     # one disclaimer per lookup


def test_disclaimer_loop_is_an_error_not_a_wall():
    http = FakeHttp(search_page=DISCLAIMER)
    out = ors.chain("Lancaster", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "error" and "search page not reached" in out["reason"]
    assert sc_polite.walled_reason("SC", "Lancaster") is None


def test_error_page_on_pick():
    http = FakeHttp(pick_status=500)
    out = ors.chain("Laurens", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "error"


def test_challenge_marks_walled_and_stops():
    http = FakeHttp(search_page="<html><title>Just a moment...</title><div class='cf-turnstile'></div></html>")
    out = ors.chain("Georgetown", OWNER, session=PoliteSession(session=http))
    assert out["status"] == "walled" and out["reason"] == "challenge page"
    again = ors.chain("Georgetown", "HOLLOWAY CEDRIC", session=PoliteSession(session=http))
    assert again["status"] == "walled" and len(http.calls) == 1


def test_empty_register():
    http = FakeHttp()
    out = ors.chain("Laurens", "NOBODY ATALL Q", session=PoliteSession(session=http))
    assert out["status"] == "not_found" and out["last_deed"] is None


def test_date_window_applied_when_register_ignores_it():
    http = FakeHttp()
    s = ors.make_searcher("SC", "Abbeville", session=PoliteSession(session=http))
    q = sc_chain.index_query("HOLLOWAY CEDRIC")
    docs = s(q, "grantee", date(2010, 1, 1))
    assert [d.book for d in docs] == ["790"]          # the 2019 row is outside the window


def test_search_by_name_unknown_county():
    assert asyncio.run(ors.search_by_name("SC", "Spartanburg", OWNER)) == []
    assert asyncio.run(ors.search_by_name("NC", "Laurens", OWNER)) == []


def test_batches_split_by_names_and_rows():
    P = ors.PickName
    picks = [P("A", "A", 150), P("B", "B", 100), P("C", "C", None), P("D", "D", 10), P("E", "E", 10),
             P("F", "F", 10), P("G", "G", 10), P("H", "H", 10)]
    out = [[p.entity_id for p in b] for b in ors.batches(picks)]
    assert out == [["A"], ["B", "C", "D", "E", "F", "G"], ["H"]]
