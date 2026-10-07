"""BIS 'Online Record System' adapter (rod/nc_ors.py) on hand-written pages shaped like the live
search form (both field styles), pick screen and NameDisplay list (made-up names, books, pages; no
fetched content). Covers the parse (with and without an Amount column), the request sequence, an
empty answer, an error page, a blocked page and a CAPTCHA (walled, never retried), and chain()."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.rod import nc_ors as ors
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, SERVER_ERROR, FakeResp, install

FORM_SPLIT = """<html><body>Instruments Verified Through: October 01, 2026
<form method="post" action="NamePick.php" id="frmlookup_form" name="frmlookup_form">
<input type="radio" name="search_type" value="Standard" checked="checked"/>
<input type="radio" name="sort_type" value="Date"/><input type="radio" name="party_type" value="Both" checked="checked"/>
<input type="radio" name="entity_type" value="both" checked/><input type="radio" name="entity_type" value="company"/>
<input type="text" name="tor_last_name"/><input type="text" name="tor_first_name"/>
<input type="checkbox" name="search_each" id="search_each" checked/>
<input type="text" name="tee_last_name"/><input type="text" name="tee_first_name"/>
<input type="text" name="start_date"/><input type="text" name="end_date"/>
<input type="checkbox" name="instType[ALL]" value="ALL"/>
<input type="checkbox" name="instType[InstCodes][D/T]" value="D/T"/>
</form></body></html>"""

FORM_SINGLE = """<html><body>
<form method="post" action="exampleNamePick.php" id="frmlookup_form" name="frmlookup_form">
<input type="radio" name="search_type" value="Standard" checked="checked"/>
<input type="radio" name="party_type" value="Both" checked="checked"/>
<input type="radio" name="entity_type" value="Both" checked="checked"/>
<input type="text" name="last_name"/><input type="text" name="first_name"/>
<input type="text" name="start_date"/><input type="text" name="end_date"/>
<input type="checkbox" name="instType[ALL]" value="ALL"/>
<input type="checkbox" name="instType[DEEDS][DEED]" value="DEED"/>
<input type="checkbox" name="instType[MORTGAGE][D/T]" value="D/T"/>
<input type="checkbox" name="instType[MORTGAGE][SAT D/T]" value="SAT D/T"/>
</form></body></html>"""
DISCLAIMER = """<html><body><form method="post" action="exampleNameSearch.php">
<input type="submit" value="Accept" name="Accept" id="Accept"/></form></body></html>"""


def pick_page(names, display_action="NameDisplay.php"):
    rows = "".join(f"<tr bgcolor = '#FFFFFF'><td class='one' align = 'center' > <input type = 'checkbox' value = '{eid}' "
                   f"name = 'entityID[{eid}]' id='{eid}' onchange=\"updateRecCount('{cnt}','{eid}')\"></td> "
                   f"<td class='two'>{last} &nbsp;</td> <td class='three'>{first} &nbsp;</td> "
                   f"<td class='four'>{cnt} &nbsp;</td></tr>" for eid, last, first, cnt in names)
    return (f"<html><body><b>Name Pick Screen</b> {len(names)} Names Found <table>"
            f"<form name='frm' id='frm' method='post' action='{display_action}'>"
            "<input type='hidden' name='igheader' value='ALL'><input type='hidden' name='igquerystring' value='('>"
            "<tr><td colspan = 4><input type = 'submit' value = 'Display Detail Listing' name='displaybutton'></td></tr>"
            "<tr><td>&nbsp;</td><td>Last Name</td><td>First Name</td><td>Count</td></tr>"
            f"{rows}</form></table></body></html>")


NO_NAMES = ("<html><body><b>Example County Register of Deeds Name Pick Screen</b> 0 Names Found / &nbsp;Records "
            "Found <table><tr><td>Search Name</td></tr></table></body></html>")

HEAD7 = ("<tr><td width='7%'><b>Date</td><td> <b>Code-Book-Page</td><td> <b>Type</td><td><b> Description</td>"
         "<td><b>One Reverse Party / D Status</td><td> <b>Cross-Ref</td><td> <b>Img? </td></tr>")
HEAD8 = ("<tr><td><b>Date</td><td><b>Code-Book-Page</td><td><b>Type</td><td><b>Description</td><td><b>Amount</td>"
         "<td><b>Reverse Party</td><td><b>Cross-Ref</td><td><b>Img?</td></tr>")


def block(name, role, head, rows):
    return (f"<tr><td colspan = 7><b><font size='4'>{name}</font></b></td></tr>"
            f"<tr><td colspan = 7 bgcolor = '#CCCCCC'> <b>{name} ({role}) </b></td></tr>{head}{''.join(rows)}")


def row7(inst, date, cbp, typ, desc, reverse, xref=""):
    x = f'<a href="DetailScreen.php?inst_num={inst}9"> {xref}</a><br> &nbsp;' if xref else "&nbsp;"
    return (f'<tr bgcolor="#FFFFFF"><td> <a href="DetailScreen.php?inst_num={inst}"> {date}</a></td> '
            f"<td>{cbp} &nbsp;</td> <td>{typ} &nbsp;</td> <td> {desc}&nbsp;</td> <td>{reverse} &nbsp;</td> "
            f'<td>{x}</td> <td><a href="view_image.php?file={inst}&type=pdf">PDF</a></td></tr>')


def display(*blocks):
    return ("<html><body><table><tr><td colspan='7'><b>Example County Register of Deeds Grantor - Grantee Index Display"
            "</b></td></tr>" + "".join(blocks) + "</table></body></html>")


DISPLAY_TESTER = display(
    block("TESTER ALVIN Q", "Grantor", HEAD7, [
        row7("2026000300", "01/15/2026", "RB-700-40", "LIS PENDENS", "", "EXAMPLE BANK"),
        row7("2022000200", "02/02/2022", "RB-640-88", "D/T", "EXAMPLE ACRES LT:7", "EXAMPLE BANK"),
        row7("2021000150", "06/01/2021", "RB-610-3", "SAT D/T", "", "EXAMPLE BANK", xref="D / T RB 500 12"),
    ]),
    block("TESTER ALVIN Q", "Grantee", HEAD7, [
        row7("2018000100", "03/01/2018", "RB-500-10", "DEED", "EXAMPLE ACRES LT:7", "SAMPLE CORA B",
             xref="DEED RB 350 77"),
    ]),
)
DISPLAY_SAMPLE = display(block("SAMPLE CORA B", "Grantee", HEAD7, [
    row7("2001000050", "05/05/2001", "RB-350-77", "DEED", "EXAMPLE ACRES LT:7", "DOE DELLA")]))


class Site:
    def __init__(self, form=FORM_SPLIT, accept="GET"):
        self.form, self.accept = form, accept
        self.ticked: list[str] = []

    def routes(self):
        out = []
        if self.accept == "GET":
            out.append(("GET", "NameSearch.php", FakeResp(self.form)))
        else:
            out.append(("POST", "NameSearch.php", lambda m, u, p, d: FakeResp(self.form if d == {"Accept": "Accept"}
                                                                              else DISCLAIMER)))
        out += [("POST", "NamePick.php", self.pick), ("POST", "NameDisplay.php", self.show)]
        return out

    def pick(self, method, url, params, data):
        last = data.get("tor_last_name") or data.get("last_name")
        pages = {"TESTER": pick_page([("11", "TESTER", "ALVIN Q", 4), ("12", "TESTER", "ZELDA", 3)]),
                 "SAMPLE": pick_page([("21", "SAMPLE", "CORA B", 1)])}
        return FakeResp(pages.get(last, NO_NAMES))

    def show(self, method, url, params, data):
        self.ticked = [v for k, v in data if k.startswith("entityID[")]
        return FakeResp({("11",): DISPLAY_TESTER, ("21",): DISPLAY_SAMPLE}.get(tuple(self.ticked), display()))


@pytest.fixture
def fake(monkeypatch):
    def go(routes):
        return install(monkeypatch, routes, ors.ADAPTER)
    yield go
    ors.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_search_form_both_styles():
    split = ors.parse_search_form(FORM_SPLIT)
    assert (split.action, split.style, split.entity_both, split.has_sort) == ("NamePick.php", "split", "both", True)
    single = ors.parse_search_form(FORM_SINGLE)
    assert (single.action, single.style, single.entity_both, single.has_sort) == \
        ("exampleNamePick.php", "single", "Both", False)
    assert single.categories == {"DEED": "DEEDS", "D/T": "MORTGAGE", "SAT D/T": "MORTGAGE"}
    assert ors.parse_search_form(DISCLAIMER) is None
    who = OwnerName(raw="x", last="TESTER", first="ALVIN")
    d = ors.pick_data(split, who, "grantee", "2018-03-01")
    assert d["tor_last_name"] == "TESTER" and d["search_each"] == "on" and d["party_type"] == "Grantee"
    assert d["end_date"] == "03/01/2018" and d["entity_type"] == "both" and d["sort_type"] == "Date"
    d = ors.pick_data(single, who, "both", None)
    assert d["last_name"] == "TESTER" and d["first_name"] == "ALVIN" and "search_each" not in d


def test_parse_pick_and_display():
    names, action, hidden = ors.parse_pick(pick_page([("11", "TESTER", "ALVIN Q", 4)]))
    assert [(n.entity_id, n.last, n.first, n.count) for n in names] == [("11", "TESTER", "ALVIN Q", 4)]
    assert action == "NameDisplay.php" and hidden == [("igheader", "ALL"), ("igquerystring", "(")]
    assert ors.parse_pick(NO_NAMES)[0] == [] and ors.no_names_found(NO_NAMES)
    rows = ors.parse_display(DISPLAY_TESTER)
    assert [r.book for r in rows] == ["700", "640", "610", "500"]
    lp, dt, sat, deed = rows
    assert (lp.kind, lp.grantors, lp.grantees, lp.index_code, lp.instrument_no) == \
        ("lis_pendens", ["TESTER ALVIN Q"], ["EXAMPLE BANK"], "RB", "2026000300")
    assert (dt.kind, dt.description) == ("deed_of_trust", "EXAMPLE ACRES LT:7")
    assert (sat.kind, sat.xref) == ("satisfaction", "D / T RB 500 12")
    assert (deed.kind, deed.grantors, deed.grantees, deed.recorded) == \
        ("deed", ["SAMPLE CORA B"], ["TESTER ALVIN Q"], "2018-03-01")


def test_parse_display_with_an_amount_column():
    html = display(block("TESTER ALVIN Q", "Grantor", HEAD8, [
        '<tr><td><a href="DetailScreen.php?inst_num=77">08/10/2026</a></td><td>RECORD BOOK-5057-427</td>'
        "<td>SATISFACTION</td><td>PD:EXAMPLE</td><td>105,239.55</td><td>EXAMPLE BANK</td><td></td><td></td></tr>"]))
    (r,) = ors.parse_display(html)
    assert (r.index_code, r.book, r.page, r.kind, r.grantees, r.description) == \
        ("RECORD BOOK", "5057", "427", "satisfaction", ["EXAMPLE BANK"], "PD:EXAMPLE")


def test_category_does_not_turn_a_satisfaction_into_a_mortgage():
    from foreclosure_scraper.rod.nc_chain import classify_kind
    assert classify_kind("SAT D/T", "MORTGAGE") == "satisfaction"
    assert classify_kind("D/T", "MORTGAGE") == "deed_of_trust"
    assert classify_kind("DEED", "DEEDS") == "deed"


@pytest.mark.parametrize("form,accept", [(FORM_SPLIT, "GET"), (FORM_SINGLE, "POST")])
def test_search_sequence_and_chain(fake, monkeypatch, form, accept):
    site = Site(form, accept)
    sess = fake(site.routes())
    county = "New Hanover" if accept == "GET" else "Davidson"
    if accept == "POST":
        monkeypatch.setitem(ors.COUNTIES, "Davidson", ors.OrsCounty("https://example.test", "NameSearch.php", "POST"))
        site.form = FORM_SINGLE.replace("exampleNamePick.php", "NamePick.php")
    out = ors.chain(county, "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]
    assert [d["book"] for d in out["liens"]["lis_pendens"]] == ["700"]
    assert out["liens"]["open_deeds_of_trust_est"] == 0
    first = sess.calls[0]
    if accept == "GET":
        assert first[0] == "GET" and first[1].endswith("NameSearch.php?Accept=Accept")
    else:
        assert first[0] == "POST" and first[3] == {"Accept": "Accept"}
    display_post = next(c for c in sess.calls if c[1].endswith("NameDisplay.php"))
    assert ("entityID[11]", "11") in display_post[3] and ("entityID[12]", "12") not in display_post[3]
    assert ("displaybutton", "Display Detail Listing") in display_post[3]


def test_empty_answer(fake):
    fake(Site().routes())
    res = ors.ADAPTER.search("New Hanover", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0


def test_error_pages(fake):
    fake([("GET", "NameSearch.php", FakeResp(FORM_SPLIT)), ("POST", "NamePick.php", SERVER_ERROR)])
    res = ors.ADAPTER.search("New Hanover", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and res.reason == "HTTP 500"
    fake([("GET", "NameSearch.php", FakeResp(DISCLAIMER))])
    res = ors.ADAPTER.search("New Hanover", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "did not open" in res.reason
    fake([("GET", "NameSearch.php", FakeResp(FORM_SPLIT)),
          ("POST", "NamePick.php", FakeResp("<html><body>Session expired</body></html>"))])
    res = ors.ADAPTER.search("New Hanover", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "pick list" in res.reason


@pytest.mark.parametrize("wall,reason", [(CLOUDFLARE_403, "HTTP 403"), (CAPTCHA_PAGE, "CAPTCHA")])
def test_blocked_or_captcha_is_walled_and_never_retried(fake, wall, reason):
    sess = fake([("GET", "NameSearch.php", wall)])
    res = ors.ADAPTER.search("New Hanover", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(ors.search_by_name("NC", "New Hanover", "SAMPLE CORA")) == []
    assert ors.chain("New Hanover", "TESTER ALVIN Q")["status"] == "walled"
    assert len(sess.calls) == 1


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    for county in ors.COUNTIES:
        assert g.ROD_CONFIG[("NC", county)] == ("nc_ors", ors.ENV_FLAG, "0")
