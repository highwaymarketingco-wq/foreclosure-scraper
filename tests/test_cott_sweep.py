"""Cott eSearch v4 county-wide date sweeps (rod/cott_sweep.py) and the stamps the register-checks pass
writes from them, against a scripted stand-in for the Date Range tab (made-up books, pages and names)."""
from __future__ import annotations

from datetime import date

import pytest

import foreclosure_scraper.enrichment_register_checks as E
from foreclosure_scraper.rod import county_sweeps as CS
from foreclosure_scraper.rod import cott_sweep as W
from foreclosure_scraper.rod import nc_cott_v4 as cott
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.models import Listing, ListingType
from tests._nc_rod_fakes import FakeResp, install
from tests.test_nc_rod_cott_v4 import FORM, _names, _row, grid

BASE = cott.COUNTIES["Nash"].base
P = W._P
GRID_T = "ctl00$cphMain$tcMain$tpInstruments$ucInstrumentsGridV2$cpgvInstruments"
PER_PAGE = "ctl00$cphMain$tcMain$tpInstruments$ucInstrumentsGridV2$cpInstruments_Top$ddlResultsPerPage"

KINDS = [("1,2|CRP", "DEED"), ("3|CRP", "D T"), ("4,5|CRP", "JGMT"), ("6|CRP", "SAT"), ("7|CRP", "FORCL"),
         ("8|CRP", "NOT FORCL"), ("9|CRP", "CANCEL LIS PENDENS"), ("10|CRP", "LIS PENDENS"), ("11|CRP", "REL"),
         ("12|CRP", "SUBORDINATION OF LIEN"), ("13|CRP", "CLAIM OF LIEN")]


def date_tab(selected: set[str] | None = None, kinds=KINDS, index_types=(("CRP", "CONSOLIDATED"), ("MAR", "MARRIAGES"))):
    sel = selected or set()
    ks = "".join(f'<option value="{v}"{" selected=\"selected\"" if v in sel else ""}>{n}</option>' for v, n in kinds)
    its = "".join(f'<option value="{v}"{" selected=\"selected\"" if v in sel else ""}>{n}</option>'
                  for v, n in index_types)
    return (f'<html><body><input type="hidden" name="__VIEWSTATE" value=""/>'
            f'<select name="{P}lbKinds" multiple="multiple">{ks}</select>'
            f'<select name="{P}lbIndexTypes" multiple="multiple">{its}</select>'
            f'<input name="{P}txtFiledFrom"/><input type="submit" name="{P}btnSearch" value="Search"/></body></html>')


def results(rows_html: list[str], total: int, per_page: int = 10) -> str:
    opts = "".join(f'<option value="{n}"{" selected=\"selected\"" if n == per_page else ""}>{n}</option>'
                   for n in (10, 25, 50))
    html = grid(rows_html, total)
    return html.replace("<table id=", f'<select name="{PER_PAGE}">{opts}</select>'
                                      f"<a href=\"javascript:__doPostBack(&#39;{GRID_T}&#39;,&#39;Page$2&#39;)\">2</a>"
                                      "<table id=", 1)


def mkrow(n, kind, who="TESTER, ALVIN Q", date_="03/01/2024", book="9"):
    return _row(n, date_, "CRP", kind, _names(who), _names("EXAMPLE CREDIT UNION"), "", "", book, str(n))


class Server:
    """The Date Range tab of one scripted tenant. Records the order of requests; the list selection is
    consumed by a search exactly as the live tenants do."""

    def __init__(self, rows_by_window, per_page_max=50):
        self.selected: set[str] = set()
        self.log: list[str] = []
        self.rows_by_window = rows_by_window          # callable (a, b, selected) -> list of row html
        self.per_page = 10
        self.per_page_max = per_page_max
        self.last: list[str] = []

    def __call__(self, method, url, params, data):
        data = data or {}
        if method == "GET":
            return FakeResp(FORM, 200, url)
        if "ctl00$NavMenuIdxRec$btnNav_IdxRec_Date_NEW" in data:
            self.log.append("nav")
            return FakeResp(date_tab(), 200, BASE + "SrchDate.aspx")
        tgt = data.get("__EVENTTARGET", "")
        if tgt.endswith("lbKinds") or tgt.endswith("lbIndexTypes"):
            vals = data.get(tgt) or []
            self.selected = set(vals if isinstance(vals, list) else [vals])
            self.log.append("select")
            return FakeResp(date_tab(self.selected), 200, BASE + "SrchDate.aspx")
        if tgt == PER_PAGE:
            self.per_page = int(data[PER_PAGE])
            self.log.append("perpage")
            return FakeResp(results(self.last[:self.per_page], len(self.last), self.per_page), 200, url)
        if tgt == GRID_T:
            n = int(data["__EVENTARGUMENT"].split("$")[1])
            self.log.append(f"page{n}")
            chunk = self.last[(n - 1) * self.per_page: n * self.per_page]
            return FakeResp(results(chunk, len(self.last), self.per_page), 200, url)
        if f"{P}btnSearch" in data:
            frm = data[P + "txtFiledFrom"].split("/")
            thr = data[P + "txtFiledThru"].split("/")
            a, b = date(int(frm[2]), int(frm[0]), int(frm[1])), date(int(thr[2]), int(thr[0]), int(thr[1]))
            self.log.append("search")
            self.last = self.rows_by_window(a, b, set(self.selected))
            self.selected = set()                      # consumed
            self.per_page = 10
            return FakeResp(results(self.last[:10], len(self.last)), 200, url)
        return FakeResp("<html>no route</html>", 404, url)


@pytest.fixture
def srv(monkeypatch):
    def go(rows_by_window):
        s = Server(rows_by_window)
        install(monkeypatch, [("GET", "Nash", s), ("POST", "Nash", s), ("POST", "SrchName", s),
                              ("POST", "SrchDate", s), ("GET", "SrchName", s)], cott.ADAPTER)
        return s
    yield go
    cott.ADAPTER.drop_sessions()
    nc_polite.reset_state()


# ---- pure parsers ---------------------------------------------------------------------------------

def test_adverse_kinds_are_picked_by_name_and_releases_are_not():
    names = [n for _v, n in W.adverse_options(W.parse_options(date_tab(), "lbKinds"))]
    assert names == ["JGMT", "FORCL", "NOT FORCL", "LIS PENDENS", "CLAIM OF LIEN"]
    for bad in ("SAT", "REL", "CANCEL LIS PENDENS", "SUBORDINATION OF LIEN", "DEED", "D T", "RIGHT OF FIRST REFUSAL",
                "QUIT CLAIM DEED", "DISCLAIMER"):
        assert not W.adverse_kind(bad)
    for good in ("JUDGMENT", "JDGMT", "FINALJUDGE", "LIS PEND", "NOTICE OF FORECLOSURE", "FCL", "SEWER LIEN",
                 "NOTICE OF ASSESSMENT", "ORDER & JUDGMENT"):
        assert W.adverse_kind(good)


def test_per_page_and_grid_target_and_selected_count():
    html = results([mkrow(1, "FORCL")], 30)
    assert W.per_page_control(html) == (PER_PAGE, "50", 10)
    assert W.grid_target(html) == GRID_T
    assert W.selected_count(date_tab({"4,5|CRP", "7|CRP"}), "lbKinds") == 2
    assert W.per_page_control("<html></html>") is None


def test_select_body_carries_the_event_target_and_values():
    d = W.select_body("lbKinds", ["4,5|CRP", "7|CRP"])
    assert d["__EVENTTARGET"] == P + "lbKinds" and d[P + "lbKinds"] == ["4,5|CRP", "7|CRP"] and d["__VIEWSTATE"] == ""


# ---- the lien reader ------------------------------------------------------------------------------

def test_the_kind_selection_is_posted_before_every_window(srv):
    s = srv(lambda a, b, sel: [mkrow(1, "FORCL")] if sel else [mkrow(i, "DEED") for i in range(1, 6)])
    r = W.CottLienReader("Nash")
    r.open()
    got1, ov1 = r.read(date(2024, 1, 1), date(2024, 1, 20))
    got2, ov2 = r.read(date(2024, 2, 1), date(2024, 2, 20))
    assert not ov1 and not ov2 and [x["t"] for x in got1 + got2] == ["FORCL", "FORCL"]     # filtered both times
    assert s.log == ["nav", "select", "select", "search", "select", "search"]
    assert r.types == 5


def test_paging_reads_every_row_through_the_results_per_page_list(srv):
    s = srv(lambda a, b, sel: [mkrow(i, "JGMT", who=f"DOE{i}, JOHN") for i in range(1, 38)])
    r = W.CottLienReader("Nash")
    r.open()
    got, ov = r.read(date(2024, 1, 1), date(2024, 1, 29))
    assert not ov and len(got) == 37
    assert "perpage" in s.log


def test_a_window_over_29_days_makes_no_request_and_asks_to_split(srv):
    s = srv(lambda a, b, sel: [])
    r = W.CottLienReader("Nash")
    r.open()
    before = len(s.log)
    assert r.read(date(2024, 1, 1), date(2024, 3, 1)) == ([], True)
    assert len(s.log) == before


def test_an_empty_window_is_clean(srv):
    srv(lambda a, b, sel: [])
    r = W.CottLienReader("Nash")
    r.open()
    assert r.read(date(2024, 1, 1), date(2024, 1, 20)) == ([], False)


def test_a_huge_window_is_split(srv, monkeypatch):
    srv(lambda a, b, sel: [mkrow(i, "JGMT") for i in range(1, 9)])
    monkeypatch.setattr(W, "MAX_WINDOW_ROWS", 5)
    r = W.CottLienReader("Nash")
    r.open()
    assert r.read(date(2024, 1, 1), date(2024, 1, 20)) == ([], True)


def test_a_full_sweep_finds_the_owner_and_claims_none_found_for_the_window(srv, tmp_path):
    def rows(a, b, sel):
        if a <= date(2024, 3, 5) <= b:
            return [mkrow(1, "FORCL", who="TESTER, ALVIN Q", date_="03/05/2024")]
        return []
    srv(rows)
    index, res = CS.sweep(W.CottLienReader("Nash"), since=date(2024, 1, 1), today=date(2024, 6, 30), cache_dir=tmp_path)
    assert not res.walled and not res.error and res.window_from == "2024-01-01" and res.window_to == "2024-06-30"
    hit = CS.stamp_for(index.match("TESTER ALVIN Q"), res)
    clean = CS.stamp_for(index.match("NOBODY SAMPLE"), res)
    assert hit["status"] == "found" and hit["instruments"][0]["t"] == "FORCL"
    assert clean["status"] == "none_found" and clean["window_from"] == "2024-01-01"


# ---- the marriage reader --------------------------------------------------------------------------

def test_marriage_reader_selects_the_mar_index_and_names_blank_types(srv):
    s = srv(lambda a, b, sel: [_row(1, "06/01/2024", "MAR", "", _names("TESTER, ALVIN Q"), _names("SAMPLE, CORA B"),
                                    "", "", "42", "7")] if sel == {"MAR"} else [])
    r = W.CottMarriageReader("Nash")
    r.open()
    got, ov = r.read(date(2024, 6, 1), date(2024, 6, 20))
    assert got[0]["t"] == "MARRIAGE" and got[0]["fs"] == ["TESTER, ALVIN Q"] and not ov
    assert r.key == "nc_nash_marriage"


def test_marriage_reader_without_a_mar_index_refuses(monkeypatch, srv):
    srv(lambda a, b, sel: [])
    monkeypatch.setattr(W, "parse_options", lambda html, suffix: [("CRP", "CONSOLIDATED")])
    with pytest.raises(RuntimeError):
        W.CottMarriageReader("Nash").open()


# ---- the enricher's stamping ----------------------------------------------------------------------

def _lead(owner, county="Nash", raw=None):
    return Listing(source="t", source_url="https://example.org/x", listing_type=ListingType.TAX_LIEN, state="NC",
                   county=county, owner_name=owner, raw=raw or {})


class _FakeReader(CS.Reader):
    label = "fake_sweep"
    state = "NC"

    def __init__(self, county, docs, types=3):
        self.county, self.docs, self.types = county, docs, types

    def open(self):
        pass

    def read(self, a, b):
        if (b - a).days > 29:
            return [], True
        return [d for d in self.docs if a.isoformat() <= d["d"] <= b.isoformat()], False


class _FakeMarriage(_FakeReader):
    label = "fake_marriage_sweep"

    @property
    def key(self):
        return f"{self.state}_{self.county}_marriage".lower()


def test_stamp_county_writes_both_stamps_and_never_overwrites_a_found_licence(monkeypatch, tmp_path):
    lien = _FakeReader("Onslow", [{"t": "FORCL", "d": "2025-03-05", "b": "1", "p": "2", "i": "x1",
                                   "fs": ["TESTER, ALVIN Q"], "gs": ["EXAMPLE CREDIT UNION"]}])
    mar = _FakeMarriage("Onslow", [{"t": "MARRIAGE", "d": "2025-04-01", "b": "3", "p": "4", "i": "m1",
                                  "fs": ["TESTER, ALVIN Q"], "gs": ["SAMPLE, CORA B"]}], types=1)
    monkeypatch.setattr(E, "sweep_jobs", lambda c: [("lien", lambda: lien), ("marriage", lambda: mar)])
    monkeypatch.setattr(CS, "CACHE_DIR", tmp_path)
    a, b = _lead("TESTER ALVIN Q", "Onslow"), _lead("NOBODY SAMPLE", "Onslow")
    c = _lead("TESTER ALVIN Q", "Onslow", raw={"marriage_license": {"spouse_name": "Kept Spouse", "license_date": "2001-01-01"}})
    stats = {"sweeps": [], "sweep_not_stamped": 0}
    E._stamp_county("Onslow", [a, b, c], 60.0, date(2025, 1, 1), stats)
    assert a.raw["rod_lien_sweep"]["status"] == "found" and b.raw["rod_lien_sweep"]["status"] == "none_found"
    assert a.raw["marriage_license"]["status"] == "found" and a.raw["marriage_license"]["spouse_name"] == "Cora B Sample"
    assert b.raw["marriage_license"]["status"] == "no_match" and b.raw["marriage_license"]["checked_at"]
    assert c.raw["marriage_license"]["status"] == "found"          # a found licence is replaced only by a found one
    assert stats["sweep_lien_found"] == 2 and stats["sweep_lien_none_found"] == 1


def test_a_failed_sweep_stamps_nothing(monkeypatch):
    class Boom:
        def __call__(self):
            raise RuntimeError("down")

    monkeypatch.setattr(E, "sweep_jobs", lambda c: [("lien", Boom())])
    a = _lead("TESTER ALVIN Q", "Onslow")
    stats = {"sweeps": [], "sweep_not_stamped": 0}
    E._stamp_county("Onslow", [a], 60.0, date(2025, 1, 1), stats)
    assert "rod_lien_sweep" not in a.raw and stats["sweep_not_stamped"] == 1


def test_sweep_jobs_per_county():
    assert [k for k, _ in E.sweep_jobs("Onslow")] == ["lien", "marriage"]
    assert [k for k, _ in E.sweep_jobs("Pitt")] == ["lien"]
    assert E.sweep_jobs("Rowan") == [] and E.sweep_jobs("Guilford") == []
