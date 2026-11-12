"""Logan 'Public Records' Blazor adapter (rod/nc_logan_blazor.py) on hand-written pages shaped like
the live DevExpress tabs and grids (made-up names, books, pages; no fetched content), driven through
the real rod.nc_render.RenderPage with a scripted fake browser page. Covers the parsers, the flow
(acknowledge, Full System, name, Search, tick the owner's names, View Checked), chain(), an empty
answer, an error page, a blocked page and a CAPTCHA (walled, never retried), and the registry."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.rod import nc_logan_blazor as lb
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, FakePWPage, install, install_render

ROOT = lb.COUNTIES["Catawba"].root
LANDING = ("<html><body><button id='idx1'>Acknowledge Disclaimer to Begin Searching Records</button>"
           "<button id='idx2'>Staff Login</button></body></html>")
MENU = "<html><body><button>Home</button><button>Full System</button><button>Imaging</button></body></html>"
FORM = ("<html><body><dxbl-tab-item>Index Search</dxbl-tab-item><dxbl-tab-item>Directory (0) Directory (0)</dxbl-tab-item>"
        "<dxbl-tab-item>Index Detail (0) Index Detail (0)</dxbl-tab-item><label>Human</label><label>Corp</label>"
        "<label>Last Name</label><input/><label>Given Name</label><input/><label>Start Date</label><input/>"
        "<label>End Date</label><input/><button>Search</button></body></html>")
DETAIL_HEADS = ["", "Selection Select All", "Index", "C", "Series", "Name", "Reverse Party", "Description", "Rec Date",
                "Type", "Book/Page", ""]


def tabs(directory, detail):
    return (f"<dxbl-tab-item>Index Search</dxbl-tab-item><dxbl-tab-item>Directory ({directory}) Directory ({directory})"
            f"</dxbl-tab-item><dxbl-tab-item>Index Detail ({detail}) Index Detail ({detail})</dxbl-tab-item>")


def directory_grid(names):
    rows = "".join(f'<tr data-visible-index="{i}"><td class="dxbl-grid-selection-cell"><dxbl-check></dxbl-check></td>'
                   f'<td role="gridcell"><a>{n}</a></td><td role="gridcell">{c}</td><td></td></tr>'
                   for i, (n, c) in enumerate(names))
    return ("<dxbl-grid><table><tr><th>Selection Select All</th><th>Name</th><th>Entries</th><th></th></tr>"
            f"{rows}</table></dxbl-grid>")


def detail_grid(rows):
    head = "".join(f"<th>{h}</th>" for h in DETAIL_HEADS)
    body = "".join(f'<tr data-visible-index="{i}"><td></td><td></td><td>Land</td><td></td><td>{series}</td><td>{name}</td>'
                   f"<td>{rev}</td><td>{desc}</td><td>{date}</td><td>{kind}</td><td>{bp}</td><td></td></tr>"
                   for i, (series, name, rev, desc, date, kind, bp) in enumerate(rows))
    return f"<dxbl-grid><table><tr>{head}</tr>{body}</table></dxbl-grid>"


TESTER_DIR = [("TESTER, ALVIN Q", 4), ("TESTER, ZELDA", 9)]
TESTER_ROWS = [("2-Grantee", "TESTER, ALVIN Q", "EXAMPLE BANK", "", "01/15/2026", "LIS P", "07000 / 0040"),
               ("1-Grantor", "TESTER, ALVIN Q", "EXAMPLE BANK", "LT7 EXAMPLE ACRES", "02/02/2022", "D T", "06400 / 0088"),
               ("1-Grantor", "TESTER, ALVIN Q", "EXAMPLE BANK", "", "06/01/2021", "SAT", "06100 / 0003"),
               ("2-Grantee", "TESTER, ALVIN Q", "SAMPLE, CORA B", "LT7 EXAMPLE ACRES", "03/01/2018", "DEED", "05000 / 0010")]
SAMPLE_DIR = [("SAMPLE, CORA B", 1)]
SAMPLE_ROWS = [("2-Grantee", "SAMPLE, CORA B", "DOE, DELLA", "LT7 EXAMPLE ACRES", "05/05/2001", "DEED", "03500 / 0077")]
PRESENT = {lb.ACK: "Acknowledge Disclaimer", lb.FULL_SYSTEM: "Full System", lb.labeled("Last Name"): "Last Name"}


def site(landing=LANDING, form=FORM):
    def search(page):
        last = page.typed.get(lb.labeled("Last Name"), "")
        names = TESTER_DIR if last == "TESTER" else SAMPLE_DIR if last == "SAMPLE" else []
        return (ROOT + "FullSystem", f"<html><body>{tabs(len(names), 0)}{directory_grid(names)}{detail_grid([])}</body></html>")

    def view(page):
        ticked = [sel for kind, sel in page.log if kind == "click" and "dxbl-check" in sel]
        last = page.typed.get(lb.labeled("Last Name"), "")
        rows = (TESTER_ROWS if last == "TESTER" else SAMPLE_ROWS) if ticked else []
        names = TESTER_DIR if last == "TESTER" else SAMPLE_DIR
        return (ROOT + "FullSystem",
                f"<html><body>{tabs(len(names), len(rows))}{directory_grid(names)}{detail_grid(rows)}</body></html>")

    return FakePWPage({ROOT: landing}, {lb.ACK: (ROOT, MENU), lb.FULL_SYSTEM: (ROOT + "FullSystem", form),
                                        lb.SEARCH: search, lb.VIEW_CHECKED: view}, present=PRESENT)


@pytest.fixture
def fake(monkeypatch):
    made: list[FakePWPage] = []

    def go(**kw):
        install(monkeypatch, [], lb.ADAPTER)
        install_render(monkeypatch, lambda: made.append(site(**kw)) or made[-1])
        return made
    yield go
    lb.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_parsers():
    html = f"<html>{tabs(2, 4)}{directory_grid(TESTER_DIR)}{detail_grid(TESTER_ROWS)}</html>"
    assert lb.tab_counts(html) == {"directory": 2, "index detail": 4}
    assert lb.parse_directory(html) == [(0, "TESTER, ALVIN Q", 4), (1, "TESTER, ZELDA", 9)]
    sided = lb.parse_detail_sides(html)
    assert [s for _, s in sided] == ["grantee", "grantor", "grantor", "grantee"]
    lp, dt, sat, deed = [r for r, _ in sided]
    assert (lp.kind, lp.grantors, lp.grantees, lp.book, lp.page) == ("lis_pendens", ["EXAMPLE BANK"],
                                                                     ["TESTER, ALVIN Q"], "7000", "40")
    assert (dt.kind, dt.description, dt.recorded) == ("deed_of_trust", "LT7 EXAMPLE ACRES", "2022-02-02")
    assert (sat.kind, deed.kind, deed.grantors) == ("satisfaction", "deed", ["SAMPLE, CORA B"])


def test_flow_and_chain(fake):
    made = fake()
    out = lb.chain("Catawba", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "5000"
    assert [p["book"] for p in out["prior_instruments"]] == ["3500"]
    assert out["liens"]["open_deeds_of_trust_est"] == 0 and [d["book"] for d in out["liens"]["lis_pendens"]] == ["7000"]
    first = made[0]
    clicks = [sel for kind, sel in first.log if kind == "click"]
    assert clicks[:3] == [lb.ACK, lb.FULL_SYSTEM, lb.radio("Human")]
    assert lb.directory_check(0) in clicks and lb.directory_check(1) not in clicks       # only the owner's name
    assert first.typed[lb.labeled("Last Name")] == "TESTER" and first.typed[lb.labeled("Given Name")] == "ALVIN"
    walk = made[1]
    assert walk.typed[lb.labeled("End Date")] == "03/01/2018" and walk.typed[lb.labeled("Last Name")] == "SAMPLE"


def test_grantee_side_filter(fake):
    fake()
    res = lb.ADAPTER.search("Catawba", OwnerName(raw="x", last="TESTER", first="ALVIN"), "grantee", None)
    assert res.status == "ok" and [r.book for r in res.records] == ["7000", "5000"]


def test_empty_and_errors(fake):
    fake()
    res = lb.ADAPTER.search("Catawba", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0
    fake(landing="<html><body>The site is down for maintenance</body></html>")
    res = lb.ADAPTER.search("Catawba", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "menu did not open" in res.reason
    fake(form="<html><body>An unhandled error has occurred. Reload</body></html>")
    res = lb.ADAPTER.search("Catawba", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "did not open" in res.reason


@pytest.mark.parametrize("wall,reason", [((403, CLOUDFLARE_403.text), "HTTP 403"), (CAPTCHA_PAGE.text, "CAPTCHA")])
def test_blocked_is_walled_and_never_retried(fake, wall, reason):
    made = fake(landing=wall)
    res = lb.ADAPTER.search("Catawba", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(lb.search_by_name("NC", "Catawba", "SAMPLE CORA")) == []
    assert lb.chain("Catawba", "TESTER ALVIN Q")["status"] == "walled"
    assert len(made) == 1 and made[0].log == [("goto", ROOT)]


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    for county in lb.COUNTIES:
        assert g.RENDER_ROD_CONFIG[("NC", county)] == ("nc_logan_blazor", lb.ENV_FLAG, "0")
        assert ("NC", county) not in g.ROD_CONFIG
