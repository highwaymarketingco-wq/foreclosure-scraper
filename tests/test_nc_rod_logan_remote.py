"""Logan 'Remote Access' Visual WebGui adapter (rod/nc_logan_remote.py) on hand-written pages shaped
like the live search.wgx grids (made-up names, books, pages; no fetched content), driven through the
real rod.nc_render.RenderPage with a scripted fake browser page. Covers the grid parsers, the flow
(acknowledge, name, dates set in one step, Search, Directory, tick the owner's rows by structure,
View Checked, Index/Detail), the recorded-date limits, chain(), an empty answer, an error page, a
blocked page and a CAPTCHA (walled, never retried), and the registry."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.rod import nc_logan_remote as lr
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, FakePWPage, install, install_render

ROOT = lr.COUNTIES["Vance"].root
LANDING = "<html><body><a href='welcome.asp'>Acknowledge Disclaimer to Begin Searching Records</a></body></html>"
WELCOME = "<html><body><a href='SearchStart.aspx'>Full System</a></body></html>"
SEARCH_PAGE = ("<html><body><span id='TXT_12'>Directory</span><span id='TXT_13'>Index/Detail</span>"
               "<span>Search</span><span>Surname (last name)</span><input id='TRG_56'/><span>Given Name</span>"
               "<input id='TRG_65'/><span>Start Date (mm/dd/yyyy)</span><input id='TRG_62'/>"
               "<span>End Date (mm/dd/yyyy)</span><input id='TRG_61'/><span>Human</span><span>Non-Human</span>"
               "</body></html>")
BESIDE = {lr.SURNAME: "TRG_56", lr.GIVEN: "TRG_65", lr.START: "TRG_62", lr.END: "TRG_61"}
DETAIL_HEADS = ["", "C", "Series", "Name", "Reverse Party", "Description", "Rec Date", "Type", "Book/Page"]


def grid(gid, heads, rows):
    h = "".join(f'<div id="VWG_{gid}_C{i}">{x}</div>' for i, x in enumerate(heads))
    r = "".join(f'<div id="VWGROW2_{gid}_R{n}">' + "".join(f'<div id="VWG_{gid}_D{i}">{c}</div>' for i, c in enumerate(cells))
                + "</div>" for n, cells in enumerate(rows))
    return f"<div>{h}</div><div>{r}</div>"


def dir_grid(names):
    return grid("126", ["", "Name", "Entries"],
                [["<div tabindex='-1' data-vwgfocuselement='1'><table><tr><td></td></tr></table></div>",
                  f"<span>{n}</span>", str(c)] for n, c in names])


def det_grid(rows):
    return grid("143", DETAIL_HEADS, [["", ""] + list(r) for r in rows])


TESTER_DIR = [("TESTER, ALVIN Q", 4), ("TESTER, ZELDA", 9)]
TESTER_ROWS = [("2-Grantee", "TESTER, ALVIN Q", "EXAMPLE BANK", "", "01/15/2026", "LIS-P", "00700 / 0040"),
               ("1-Grantor", "TESTER, ALVIN Q", "EXAMPLE BANK", "2 TRACTS", "02/02/2022", "D-T", "00640 / 0088"),
               ("1-Grantor", "TESTER, ALVIN Q", "EXAMPLE BANK", "500-12", "06/01/2021", "SAT", "00610 / 0003"),
               ("2-Grantee", "TESTER, ALVIN Q", "SAMPLE, CORA B", "LOT 7 EXAMPLE ACRES", "03/01/2018", "DEED",
                "00500 / 0010")]
SAMPLE_DIR = [("SAMPLE, CORA B", 2)]
SAMPLE_ROWS = [("2-Grantee", "SAMPLE, CORA B", "DOE, DELLA", "LOT 7 EXAMPLE ACRES", "05/05/2001", "DEED", "00350 / 0077"),
               ("1-Grantor", "SAMPLE, CORA B", "SOMEONE ELSE", "LOT 9", "07/07/2019", "DEED", "00520 / 0001")]


def site(landing=LANDING, search_page=SEARCH_PAGE):
    def names(page):
        last = page.typed.get("#TRG_56", "")
        return TESTER_DIR if last == "TESTER" else SAMPLE_DIR if last == "SAMPLE" else []

    def directory(page):
        return (ROOT + "search.wgx", f"<html><body>{SEARCH_PAGE}{dir_grid(names(page))}</body></html>")

    def detail(page):
        ticked = [sel for kind, sel in page.log if kind == "click" and "data-vwgfocuselement" in sel]
        last = page.typed.get("#TRG_56", "")
        rows = (TESTER_ROWS if last == "TESTER" else SAMPLE_ROWS) if ticked else []
        return (ROOT + "search.wgx", f"<html><body>{SEARCH_PAGE}{dir_grid(names(page))}{det_grid(rows)}</body></html>")

    p = FakePWPage({"SearchStart.aspx": search_page, ROOT: landing},
                   {lr.ACK: (ROOT + "welcome.asp", WELCOME), lr.SEARCH: (ROOT + "search.wgx", SEARCH_PAGE),
                    lr.DIRECTORY_TAB: directory, lr.VIEW_CHECKED: directory, lr.DETAIL_TAB: detail},
                   present={f"span:text-is('{lr.SURNAME}')": lr.SURNAME})
    p.beside = BESIDE
    return p


@pytest.fixture
def fake(monkeypatch):
    made: list[FakePWPage] = []

    def go(**kw):
        install(monkeypatch, [], lr.ADAPTER)
        install_render(monkeypatch, lambda: made.append(site(**kw)) or made[-1])
        return made
    yield go
    lr.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_grid_parsers():
    html = dir_grid(TESTER_DIR) + det_grid(TESTER_ROWS)
    g, names, col = lr.directory(html)
    assert (g, col) == ("126", 0) and names == [(0, "TESTER, ALVIN Q", 4), (1, "TESTER, ZELDA", 9)]
    sided = lr.detail(html)
    assert [s for _, s in sided] == ["grantee", "grantor", "grantor", "grantee"]
    lp, dt, sat, deed = [r for r, _ in sided]
    assert (lp.kind, lp.grantors, lp.grantees, lp.book, lp.page) == ("lis_pendens", ["EXAMPLE BANK"],
                                                                     ["TESTER, ALVIN Q"], "700", "40")
    assert (dt.kind, sat.kind, deed.kind, deed.recorded) == ("deed_of_trust", "satisfaction", "deed", "2018-03-01")
    assert lr.detail(dir_grid(TESTER_DIR)) is None and lr.directory(det_grid([]))[0] is None
    assert lr.row_check("126", 3, 0) == "#VWGROW2_126_R3 > div:nth-child(1) [data-vwgfocuselement]"


def test_flow_and_chain(fake):
    made = fake()
    out = lr.chain("Vance", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]         # the 2019 deed is after: dropped
    assert [d["book"] for d in out["liens"]["lis_pendens"]] == ["700"]
    first = made[0]
    assert ("click", lr.ACK) in first.log
    assert first.typed["#TRG_56"] == "TESTER" and first.typed["#TRG_65"] == "ALVIN"
    assert lr.row_check("126", 0, 0) in [s for k, s in first.log if k == "click"]
    assert lr.row_check("126", 1, 0) not in [s for k, s in first.log if k == "click"]   # only the owner
    assert "#TRG_61" not in first.typed                                     # no date limit on the owner search
    walk = made[1]
    assert walk.typed["#TRG_61"] == "03/01/2018" and ("fill", "#TRG_61") in walk.log


def test_entity_owner_uses_non_human(fake):
    made = fake()
    lr.ADAPTER.search("Vance", OwnerName(raw="x", last="EXAMPLE HOLDINGS LLC", entity=True))
    assert ("click", lr.name_type(True)) in made[0].log and "#TRG_65" not in made[0].typed


def test_empty_and_errors(fake):
    fake()
    res = lr.ADAPTER.search("Vance", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0
    fake(search_page="<html><body>Server Error in '/' Application.</body></html>")
    res = lr.ADAPTER.search("Vance", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "did not open" in res.reason


@pytest.mark.parametrize("wall,reason", [((403, CLOUDFLARE_403.text), "HTTP 403"), (CAPTCHA_PAGE.text, "CAPTCHA")])
def test_blocked_is_walled_and_never_retried(fake, wall, reason):
    made = fake(landing=wall)
    res = lr.ADAPTER.search("Vance", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(lr.search_by_name("NC", "Vance", "SAMPLE CORA")) == []
    assert lr.chain("Vance", "TESTER ALVIN Q")["status"] == "walled"
    assert len(made) == 1 and made[0].log == [("goto", ROOT)]


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    assert len(lr.COUNTIES) == 11
    for county in lr.COUNTIES:
        assert g.RENDER_ROD_CONFIG[("NC", county)] == ("nc_logan_remote", lr.ENV_FLAG, "0")


def test_entry_page_for_opening_asp_counties(fake, monkeypatch):
    made = fake()
    monkeypatch.setitem(lr.COUNTIES, "Vance", lr.RemoteCounty(ROOT, "opening.asp"))
    made[:] = []
    install_render(monkeypatch, lambda: made.append(site()) or made[-1])
    lr.ADAPTER.search("Vance", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert made[0].log[0] == ("goto", ROOT + "opening.asp") and ("click", lr.ACK) in made[0].log
    assert lr.COUNTIES["Warren"].entry == "opening.asp" and lr.COUNTIES["Bladen"].entry == "opening.asp"
