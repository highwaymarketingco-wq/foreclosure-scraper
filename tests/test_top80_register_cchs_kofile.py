"""Top-80 register group: CCHS classic / CCHS LRSearch / GovOS CountyFusion / GovOS-Kofile PublicSearch.

Hand-written fixtures only (made-up names, books, pages, ids), shaped like the registers' replies:
the CountyFusion guest sign-in and results frames, the LRSearch grid and marriage grid, the CCHS
classic XML, the PublicSearch WebSocket reply. Covers the parsers, the adapters' request sequences
(guest button posted with empty credentials, a wall never retried), the document-type window
reader, the county-wide sweep (bisecting an overflowing window, the cache, a budget that ends early,
a wall), the matching index, the stamps ('screened, none found' only for the window read) and the
enrichment pass.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from foreclosure_scraper import enrichment_county_lien_sweep as ES
from foreclosure_scraper.rod import county_sweeps as CS
from foreclosure_scraper.rod import nc_lrsearch as L
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod import sc_countyfusion as F
from foreclosure_scraper.rod.nc_chain import IndexRecord, OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, FakeResp, install

# ------------------------------------------------------------------------------------------------
# CountyFusion fixtures
# ------------------------------------------------------------------------------------------------

LOGIN_PAGE = ("<html><body><form name='loginform' action='login.action' method='post'>"
              "<input type=\"hidden\" name=\"token\" value=\"TOK123\" />"
              "<input type='text' name='username'><input type='password' name='password'>"
              "<input type='button' onclick='doGuestLogin(true)' value='Login as Guest'></form></body></html>")
MAIN_PAGE = "<html><body><iframe name='bodyframe' src='blank.jsp'></iframe></body></html>"
CRIT_PAGE = ("<html><script>initInstTypePanel(50, \"Document Types\");</script>"
             "<form name='searchForm' action='/countyweb/search/searchExecute.do?assessor=false'></form></html>")


def frame(count, pages=1):
    return (f"<html><script>searchResultObj = new SearchResult(); searchResultObj.noResults = {str(count == 0).lower()};"
            f" searchResultObj.numRecordPages = {pages}; searchResultObj.resultsCount = {count};</script>"
            "<iframe id='resultListFrame' src=\"SumterSC/docs_SearchResultList.jsp?scrollPos=0&searchSessionId=searchJobMain\">"
            "</iframe></html>")


def row(i, inst, bp, date_, kind, t1, n1, t2, n2, legal=""):
    def names(ns):
        ns = [ns] if isinstance(ns, str) else ns
        title = ":: ".join(ns) if len(ns) > 1 else ""
        return f'<span title="{title}">{ns[0]}</span>' + (' <a class="multiStyle">+</a>' if len(ns) > 1 else "")
    return (f"<script>documentRowInfo[{i}] = new Object(); documentRowInfo[{i}].instId = \"{9000 + i}\";"
            f" documentRowInfo[{i}].instNum = \"{inst}\";</script><tr id=\"{i}\"><td>{i + 1}&nbsp;</td>"
            f"<td><input type=\"checkbox\" name=\"navCB\"></td><td><span>{bp}</span></td><td>&nbsp;</td>"
            f"<td>{date_}</td><td>{kind}</td><td>{t1}</td><td>{names(n1)}</td><td>{t2}</td><td>{names(n2)}</td>"
            f"<td>{legal}&nbsp;</td><td></td><td><nowrap></nowrap></td></tr>")


LIST_TESTER = ("<html><table><thead><tr><th>x</th></tr></thead><tbody>"
               + row(0, "900000001", "100 / 5", "01/15/2026", "JUDGMENT", "R", "TESTER ALVIN Q", "E", "EXAMPLE BANK NA", "LT 7 PB1 PG 2")
               + row(1, "900000001", "100 / 5", "01/15/2026", "JUDGMENT", "E", "EXAMPLE BANK NA", "R", "TESTER ALVIN Q")
               + row(2, "900000002", "99 / 80 +", "03/02/2020", "MORTGAGE", "R", ["TESTER ALVIN Q", "TESTER BERTHA"], "E", "LENDER INC")
               + "</tbody></table></html>")


def fusion_routes(search_answer):
    return [("GET", "login.do?countyname=SumterSC", FakeResp("<html>forward</html>")),
            ("GET", "loginDisplay.action", FakeResp(LOGIN_PAGE)),
            ("POST", "login.action", FakeResp(MAIN_PAGE)),
            ("GET", "disclaimer.do", FakeResp("<html>disclaimer</html>")),
            ("POST", "disclaimer.do", FakeResp(MAIN_PAGE)),
            ("GET", "searchMain.do", FakeResp("<html>main</html>")),
            ("GET", "searchCriteria.do", FakeResp("<html>crit</html>")),
            ("GET", "dynCriteria.do", FakeResp(CRIT_PAGE)),
            ("POST", "searchExecute.do", search_answer),
            ("GET", "docs_SearchResultList.jsp", FakeResp(LIST_TESTER)),
            ("GET", "insttype.jsp", FakeResp("<html>tree</html>")),
            ("GET", "getInstrumentCategories.do", FakeResp(json.dumps([{"id": "Root", "text": "All", "children": [
                {"id": "Branch0", "text": "JUDGMENT", "children": [{"id": "J", "text": "JUDGMENT"},
                                                                     {"id": "JS", "text": "JUDGMENT SATISFACTION"}]},
                {"id": "Branch1", "text": "DEED", "children": [{"id": "D", "text": "DEED"},
                                                               {"id": "TLF", "text": "FEDERAL TAX LIEN"},
                                                               {"id": "TLR", "text": "TAX LIEN RELEASE"}]}]}])))]


# ------------------------------------------------------------------------------------------------
# CountyFusion parsers and adapter
# ------------------------------------------------------------------------------------------------

def test_fusion_guest_login_form_carries_no_credential():
    assert F.is_guest_login(LOGIN_PAGE)
    assert not F.is_guest_login("<html>Login as Guest only</html>")
    form = F.guest_login_form("SumterSC", F.login_token(LOGIN_PAGE))
    assert form["public"] == "true" and form["username"] == "" and form["password"] == ""
    assert form["token"] == "TOK123" and form["countyname"] == "SumterSC"


def test_fusion_result_counts_and_list_url():
    assert F.result_counts(frame(3)) == {"no_results": False, "count": 3, "pages": 1}
    assert F.result_counts(frame(0, 0))["no_results"] is True
    assert F.result_counts("<html>login</html>") is None
    assert F.list_url(frame(3)).startswith("SumterSC/docs_SearchResultList.jsp?scrollPos=0&searchSessionId=")


def test_fusion_parse_result_list_roles_and_multiple_names():
    recs = F.parse_result_list(LIST_TESTER)
    assert len(recs) == 3
    a = recs[0]
    assert (a.book, a.page, a.recorded, a.doc_type, a.instrument_no) == ("100", "5", "2026-01-15", "JUDGMENT", "900000001")
    assert a.grantors == ["TESTER ALVIN Q"] and a.grantees == ["EXAMPLE BANK NA"]
    assert recs[1].grantors == ["TESTER ALVIN Q"]              # the E-type row carries the same document
    m = recs[2]
    assert (m.book, m.page) == ("99", "80")                    # the ' +' marker is dropped
    assert m.grantors == ["TESTER ALVIN Q", "TESTER BERTHA"] and m.grantees == ["LENDER INC"]


def test_fusion_instrument_tree_and_adverse_ids():
    payload = fusion_routes(FakeResp(""))[-1][2].text
    types = F.parse_instrument_tree(payload)
    assert ("J", "JUDGMENT") in types and ("Branch0", "JUDGMENT") not in types
    assert F.adverse_type_ids(types) == ["J", "TLF"]            # satisfactions and releases excluded


def test_fusion_search_form_blank_name_sweep_vs_name_search():
    f = F.search_form("TESTER ALVIN", "grantor", None, "2025-06-30")
    assert f["ALLNAMES"] == "TESTER ALVIN" and f["PARTY"] == "7" and f["TODATE"] == "06/30/2025"
    assert f["INSTTYPEALL"] == "selected" and f["RECSPERPAGE"] == "100"
    s = F.search_form("", "both", "2024-01-01", "2024-12-31", ["J", "TLF"])
    assert s["ALLNAMES"] == "" and s["INSTTYPE"] == "J,TLF" and s["INSTTYPEALL"] == "" and s["FROMDATE"] == "01/01/2024"


def test_fusion_adapter_sequence_and_checked_negative(monkeypatch):
    def answer(method, url, params, data):
        return FakeResp(frame(3 if data["ALLNAMES"].startswith("TESTER") else 0, 1 if data["ALLNAMES"].startswith("TESTER") else 0))
    sess = install(monkeypatch, fusion_routes(answer), F.ADAPTER)
    docs, status, truncated = F.ADAPTER.search_by_name_status_sync("SC", "Sumter", "TESTER ALVIN Q")
    assert status == "ok" and not truncated and {d.doc_type for d in docs} == {"JUDGMENT", "MORTGAGE"}
    posts = [(u, d) for m, u, p, d in sess.calls if m == "POST" and "login.action" in u]
    assert posts and posts[0][1]["public"] == "true" and posts[0][1]["password"] == ""
    execs = [d for m, u, p, d in sess.calls if "searchExecute.do" in u]
    assert execs[0]["ALLNAMES"] == "TESTER ALVIN"
    docs, status, truncated = F.ADAPTER.search_by_name_status_sync("SC", "Sumter", "NOBODY HEREIN")
    assert docs == [] and status == "ok" and not truncated     # a clean "nothing indexed": a checked negative


def test_fusion_wall_is_never_retried(monkeypatch):
    sess = install(monkeypatch, fusion_routes(CLOUDFLARE_403), F.ADAPTER)
    _docs, status, _t = F.ADAPTER.search_by_name_status_sync("SC", "Sumter", "TESTER ALVIN Q")
    assert status == "walled"
    n = len(sess.calls)
    _docs, status, _t = F.ADAPTER.search_by_name_status_sync("SC", "Sumter", "OTHER PERSON")
    assert status == "walled" and len(sess.calls) == n          # nothing more went out to the walled county


def test_fusion_captcha_on_login_walls_the_county(monkeypatch):
    routes = [("GET", "login.do?countyname=SumterSC", FakeResp("<html>forward</html>")),
              ("GET", "loginDisplay.action", CAPTCHA_PAGE)]
    install(monkeypatch, routes, F.ADAPTER)
    _d, status, _t = F.ADAPTER.search_by_name_status_sync("SC", "Sumter", "TESTER ALVIN Q")
    assert status == "walled"


def test_fusion_login_page_without_guest_button_is_an_error(monkeypatch):
    routes = fusion_routes(FakeResp(frame(0, 0)))
    routes[1] = ("GET", "loginDisplay.action", FakeResp("<html><input type='password' name='password'>No guest</html>"))
    install(monkeypatch, routes, F.ADAPTER)
    _d, status, _t = F.ADAPTER.search_by_name_status_sync("SC", "Sumter", "TESTER ALVIN Q")
    assert status == "error"


# ------------------------------------------------------------------------------------------------
# LRSearch fixtures
# ------------------------------------------------------------------------------------------------

LR_PAGE = ("<html><form action=\"/BeaufortNC2/LRSearch/LRIndex\" id=\"QueryFields_ExecuteSearch\" method=\"get\">"
           "<input id=\"MaxRecordCount\" name=\"MaxRecordCount\" type=\"hidden\" value=\"5000\" />"
           "<input id=\"PageSize\" name=\"PageSize\" type=\"hidden\" value=\"15\" />"
           "<input id=\"Last\" name=\"Last\" type=\"text\" value=\"\" /><input id=\"Given\" name=\"Given\" type=\"text\" value=\"\" />"
           "<input name=\"SymbolSetOut\" type=\"checkbox\" value=\"true\" />"
           "<select id=\"SearchType\" name=\"SearchType\"><option value=\"1\">Grantor</option>"
           "<option selected=\"selected\" value=\"3\">Either</option></select></form><script>"
           "this.ExecuteSearchURL = '/BeaufortNC2/LRSearch/ExecuteSearch';</script></html>")


def grid_row(i, doc, book, page, d, kind, p1, p2, desc=""):
    def cell(cls, body):
        return f'<td class="dx_grid_cell Cell_{cls} dxgv" style="font-size:12pt;">{body}</td>'

    def party(r, n):
        return f"<table><tr><td><span style='padding-right:5px;'><b>[{r}]</b></span></td><td><span>{n}</span></td></tr></table>"
    return (f'<tr id="gridTrad_DXDataRow{i}" class="dxgvDataRow dx_grid_row"><td class="dxgvDetailButton"></td>'
            + cell("DocNo", doc) + cell("Book", book) + cell("Page", page) + cell("Date", d) + cell("Kind", kind)
            + cell("Party1", party(*p1)) + cell("Party2", party(*p2)) + cell("Description", desc)
            + cell("PrimeKey", f"1-{i}") + "</tr>")


def grid(rows, n=None, docs=None):
    n = len(rows) if n is None else n
    return ("<table id='gridTrad'><tr><td>Records per page: 15 50 100 500 Total Records: "
            f"{n} Total Documents: {docs if docs is not None else n}</td></tr>" + "".join(rows) + "</table>")


GRID_TESTER = grid([
    grid_row(0, "2025000011", "300", "40", "03/04/2025", "LIEN", ("R", "TESTER, ALVIN Q"), ("E", "EXAMPLE CREDITOR LLC"), "LOT 7"),
    grid_row(1, "2025000011", "300", "40", "03/04/2025", "LIEN", ("R", "TESTER, BERTHA"), ("E", "EXAMPLE CREDITOR LLC"), "LOT 7"),
], docs=1)

MARRIAGE_PAGE = ("<html><form action=\"/BeaufortNC2/VRMarriageSearch/MarriageIndex\" id=\"QueryFields_ExecuteSearch\">"
                 "<input name=\"last\" type=\"text\" value=\"\" /><input name=\"given\" type=\"text\" value=\"\" />"
                 "<input name=\"fromdate\" type=\"text\" value=\"\" /><input name=\"todate\" type=\"text\" value=\"\" />"
                 "<select name=\"PartyType\"><option selected=\"selected\" value=\"0\">Either</option></select></form>"
                 "<script>x='/BeaufortNC2/VRMarriageSearch/ExecuteSearch'</script></html>")


def marriage_row(i, d, s2, g2, s1, g1, book, page, lic, issued):
    tds = ["", "&nbsp;", str(i + 1), "", d, s2, g2, s1, g1, book, page, lic, issued, f"1-{lic}"]
    return f'<tr id="gridTrad_DXDataRow{i}" class="dxgvDataRow">' + "".join(f"<td>{t}</td>" for t in tds) + "</tr>"


DOC_TYPES = json.dumps([[["LIEN", "LIEN", "REAL ESTATE", "48"], ["LIS/P", "LIS PENDENS", "REAL ESTATE", "49"],
                         ["JGMT", "JUDGEMENT", "REAL ESTATE", "46"], ["N/S", "NOTICE OF SATISFACTION", "REAL ESTATE", "67"],
                         ["DEED", "DEED", "REAL ESTATE", "1"]], []])


def test_lr_form_defaults_posts_hidden_and_selected_not_unchecked_boxes():
    d = L.form_defaults(LR_PAGE)
    assert d["MaxRecordCount"] == "5000" and d["PageSize"] == "15" and d["SearchType"] == "3" and "SymbolSetOut" not in d


def test_lr_parse_grid_roles_and_totals():
    assert L.totals(GRID_TESTER) == (2, 1)
    recs = L.parse_grid(GRID_TESTER)
    assert len(recs) == 2 and recs[0].recorded == "2025-03-04" and recs[0].doc_type == "LIEN"
    assert recs[0].grantors == ["TESTER, ALVIN Q"] and recs[0].grantees == ["EXAMPLE CREDITOR LLC"]
    assert recs[0].instrument_no == "2025000011" and recs[0].description == "LOT 7"


def test_lr_doc_types_and_adverse_codes_exclude_satisfactions():
    assert L.adverse_codes(L.parse_doc_types(DOC_TYPES)) == ["LIEN", "LIS/P", "JGMT"]
    assert L.parse_doc_types("not json") == []


def test_lr_window_form_is_the_advanced_search():
    f = L.window_form({"Last": "x", "PageSize": "15"}, ["LIEN", "JGMT"], "2024-01-01", "2024-12-31")
    assert f["IsAdvancedSearch"] == "True" and f["DocTypes"] == "LIEN,JGMT" and f["Last"] == ""
    assert f["AdvancedFromDate"] == "01/01/2024" and f["AdvancedToDate"] == "12/31/2024" and f["PageSize"] == "500"


def test_lr_marriage_grid_positions():
    html = grid([marriage_row(0, "09/12/2026", "ROE", "JANE M", "DOE", "RICHARD A", "42", "155", "29257", "09/04/2026")])
    rows = L.parse_marriage_grid(html)
    assert rows == [{"date": "2026-09-12", "issued": "2026-09-04", "license_no": "29257", "book": "42", "page": "155",
                     "a1": "DOE, RICHARD A", "a2": "ROE, JANE M"}]


def lr_routes(answer):
    return [("GET", "LRSearch/LRIndex", FakeResp(LR_PAGE)), ("POST", "LRSearch/ExecuteSearch", answer),
            ("GET", "LRSearch/GetDocTypes", FakeResp(DOC_TYPES)),
            ("GET", "VRMarriageSearch/MarriageIndex", FakeResp(MARRIAGE_PAGE))]


def test_lr_adapter_name_search_and_checked_negative(monkeypatch):
    sess = install(monkeypatch, lr_routes(lambda m, u, p, d: FakeResp(GRID_TESTER if d["Last"] == "TESTER" else grid([]))), L.ADAPTER)
    docs, status, truncated = L.ADAPTER.search_by_name_status_sync("NC", "Beaufort", "TESTER ALVIN Q")
    assert status == "ok" and not truncated and len(docs) == 1 and docs[0].doc_type == "LIEN"
    post = [d for m, u, p, d in sess.calls if m == "POST"][0]
    assert post["Last"] == "TESTER" and post["Given"] == "ALVIN" and post["PageSize"] == "500"
    docs, status, _t = L.ADAPTER.search_by_name_status_sync("NC", "Beaufort", "NOBODY HEREIN")
    assert docs == [] and status == "ok"
    assert not any(u.rstrip("/").endswith("BeaufortNC2") for m, u, p, d in sess.calls)   # the landing page is never fetched


def test_name_adapters_drop_a_trailing_comma_before_parsing(monkeypatch):
    sess = install(monkeypatch, lr_routes(lambda m, u, p, d: FakeResp(grid([]))), L.ADAPTER)
    L.ADAPTER.search_by_name_status_sync("NC", "Beaufort", "TESTER ALVIN Q,")
    post = [d for m, u, p, d in sess.calls if m == "POST"][0]
    assert post["Last"] == "TESTER" and post["Given"] == "ALVIN"       # not a surname-only search
    assert F.clean_name("TESTER ALVIN Q , ;") == "TESTER ALVIN Q" and L.clean_name(None) == ""


# ------------------------------------------------------------------------------------------------
# the sweep core
# ------------------------------------------------------------------------------------------------

class FakeReader(CS.Reader):
    label = "fake_sweep"
    state = "NC"
    county = "Testco"
    types = 2

    def __init__(self, docs, cap=3, fail_at=None):
        self.docs, self.cap, self.calls, self.opened, self.fail_at = docs, cap, [], 0, fail_at

    def open(self):
        self.opened += 1

    def read(self, a, b):
        self.calls.append((a, b))
        if self.fail_at and len(self.calls) >= self.fail_at:
            raise nc_polite.RodWalled("https://x", "challenge page")
        got = [s for s in self.docs if a.isoformat() <= s["d"] <= b.isoformat()]
        return ([], True) if len(got) > self.cap else (list(got), False)


def sdoc(d, i, t="LIEN", fs=("TESTER, ALVIN Q",), gs=("EXAMPLE CREDITOR LLC",)):
    return {"t": t, "d": d, "b": "300", "p": str(i), "i": f"2025{i:06d}", "fs": list(fs), "gs": list(gs)}


def test_read_back_bisects_an_overflowing_window_and_reports_full_coverage():
    docs = [sdoc("2025-03-0%d" % i, i) for i in range(1, 6)] + [sdoc("2025-11-10", 9)]
    rd = FakeReader(docs, cap=3)
    got, cov = CS.read_back(rd.read, date(2025, 12, 31), date(2025, 1, 1), lambda: False, [0])
    assert cov == date(2025, 1, 1) and len(got) == 6 and len({d["p"] for d in got}) == 6


def test_read_back_a_day_that_still_overflows_is_not_claimed():
    docs = [sdoc("2025-03-05", i) for i in range(1, 6)]
    rd = FakeReader(docs, cap=3)
    got, cov = CS.read_back(rd.read, date(2025, 12, 31), date(2025, 1, 1), lambda: False, [0])
    assert cov > date(2025, 3, 5)                                # the window from that day back is not claimed


def test_sweep_claims_only_what_it_read_when_the_budget_ends(tmp_path):
    docs = [sdoc("2024-06-01", 1), sdoc("2025-06-01", 2)]
    rd = FakeReader(docs)
    ticks = iter([0.0, 0.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0])
    idx, res = CS.sweep(rd, since=date(2024, 1, 1), today=date(2025, 12, 31), budget_s=100, clock=lambda: next(ticks),
                        cache_dir=tmp_path)
    assert res.budget_exhausted and res.window_from == "2025-01-01" and res.window_to == "2025-12-31"
    hit = CS.stamp_for(idx.match("TESTER ALVIN Q"), res)
    assert hit["status"] == "found" and hit["window_from"] == "2025-01-01"    # the 2024 lien is outside the claimed window


def test_sweep_cache_makes_the_next_run_read_only_the_new_end(tmp_path):
    docs = [sdoc("2024-06-01", 1), sdoc("2025-06-01", 2)]
    rd = FakeReader(docs)
    idx, res = CS.sweep(rd, since=date(2024, 1, 1), today=date(2025, 12, 31), cache_dir=tmp_path)
    assert res.window_from == "2024-01-01" and idx.size == 2
    first_calls = len(rd.calls)
    rd2 = FakeReader(docs + [sdoc("2026-01-10", 3)])
    idx, res = CS.sweep(rd2, since=date(2024, 1, 1), today=date(2026, 1, 20), cache_dir=tmp_path)
    assert res.window_from == "2024-01-01" and res.window_to == "2026-01-20" and idx.size == 3
    assert first_calls == 2 and len(rd2.calls) == 2 and all(a >= date(2025, 12, 1) for a, _b in rd2.calls)


def test_sweep_extends_back_when_since_moves_earlier(tmp_path):
    rd = FakeReader([sdoc("2024-06-01", 1), sdoc("2023-02-02", 4)])
    CS.sweep(rd, since=date(2024, 1, 1), today=date(2024, 12, 31), cache_dir=tmp_path)
    rd2 = FakeReader([sdoc("2024-06-01", 1), sdoc("2023-02-02", 4)])
    idx, res = CS.sweep(rd2, since=date(2023, 1, 1), today=date(2024, 12, 31), cache_dir=tmp_path)
    assert res.window_from == "2023-01-01" and idx.size == 2


def test_sweep_wall_stamps_nothing_and_keeps_the_cache(tmp_path):
    rd = FakeReader([sdoc("2025-06-01", 2)], fail_at=1)
    idx, res = CS.sweep(rd, since=date(2025, 1, 1), today=date(2025, 12, 31), cache_dir=tmp_path)
    assert res.walled == "challenge page" and res.window_from is None
    assert CS.stamp_for(idx.match("TESTER ALVIN Q"), res) is None
    assert not list(tmp_path.glob("*.json"))


def test_sweep_error_in_open_is_reported(tmp_path):
    rd = FakeReader([])
    rd.open = lambda: (_ for _ in ()).throw(RuntimeError("the search page did not open"))
    idx, res = CS.sweep(rd, since=date(2025, 1, 1), today=date(2025, 12, 31), cache_dir=tmp_path)
    assert res.error and "did not open" in res.error and res.window_from is None


# ------------------------------------------------------------------------------------------------
# matching and the stamps
# ------------------------------------------------------------------------------------------------

def test_party_index_matches_each_party_and_ranks_exact_before_name_only():
    idx = CS.PartyIndex()
    idx.add(sdoc("2025-03-01", 1, fs=("TESTER, ALVIN Q", "TESTER, BERTHA")))
    idx.add(sdoc("2024-03-01", 2, fs=("TESTER, ALVIN",)))
    idx.add(sdoc("2023-03-01", 3, fs=("OTHERNAME, CARL",), gs=("TESTER, ZED",)))
    hits = idx.match("TESTER ALVIN Q")
    assert [h["p"] for h in hits] == ["1", "2"] and [h["fit"] for h in hits] == ["exact", "name"]
    assert [h["p"] for h in idx.match("TESTER BERTHA")] == ["1"]
    assert idx.match("TESTER ZED")[0]["p"] == "3" and idx.match("NOMATCH PERSON") == []
    assert idx.match("") is None


def test_party_index_matches_an_entity_by_its_words():
    idx = CS.PartyIndex()
    idx.add(sdoc("2025-03-01", 1, fs=("SAMPLE HOLDINGS LLC",)))
    assert idx.match("SAMPLE HOLDINGS LLC")[0]["fit"] == "exact"


def test_stamp_status_found_possible_none_found():
    res = CS.SweepResult(county="Testco", state="NC", platform="fake_sweep", window_from="2016-01-01",
                         window_to="2026-10-09", types=7)
    idx = CS.PartyIndex()
    idx.add(sdoc("2025-03-01", 1))
    idx.add(sdoc("2024-03-01", 2, fs=("ZETA, PAT",)))
    s = CS.stamp_for(idx.match("TESTER ALVIN Q"), res, "2026-10-09")
    assert (s["status"], s["adverse_count"], s["window_from"], s["platform"]) == ("found", 1, "2016-01-01", "fake_sweep")
    assert CS.stamp_for(idx.match("TESTER ALVIN"), res)["status"] == "possible"
    n = CS.stamp_for(idx.match("NOBODY HEREIN"), res)
    assert n["status"] == "none_found" and n["instruments"] == [] and n["window_to"] == "2026-10-09"
    assert CS.stamp_for(None, res) is None                       # an unmatchable name is not "none found"
    res.walled = "challenge page"
    assert CS.stamp_for(idx.match("TESTER ALVIN Q"), res) is None


def test_marriage_stamp_found_no_match_and_entity():
    res = CS.SweepResult(county="Testco", state="NC", platform="m_sweep", window_from="2021-01-01", window_to="2026-10-09")
    idx = CS.PartyIndex()
    idx.add({"t": "MARRIAGE", "d": "2026-09-12", "x": "2026-09-04", "i": "29257", "b": "42", "p": "155",
             "fs": ["DOE, RICHARD A"], "gs": ["ROE, JANE M"]})
    s = CS.marriage_stamp(idx.match("DOE RICHARD A", keep_parties=True), "DOE RICHARD A", res, "Testco")
    assert s["status"] == "found" and s["spouse_name"] == "Jane M Roe" and s["license_date"] == "2026-09-04"
    assert s["marriage_date"] == "2026-09-12" and s["license_no"] == "29257" and s["match_confidence"] == "high"
    n = CS.marriage_stamp(idx.match("NOBODY HEREIN", keep_parties=True), "NOBODY HEREIN", res, "Testco")
    assert n["status"] == "no_match" and n["checked_at"] and n["window_from"] == "2021-01-01"
    assert CS.marriage_stamp([], "SAMPLE HOLDINGS LLC", res, "Testco") is None


# ------------------------------------------------------------------------------------------------
# the readers on canned register replies
# ------------------------------------------------------------------------------------------------

def test_lrsearch_reader_reads_a_window_and_flags_overflow(monkeypatch):
    big = grid([grid_row(0, "1", "1", "1", "01/02/2025", "LIEN", ("R", "A, B"), ("E", "C"))], n=600)
    answers = [FakeResp(GRID_TESTER), FakeResp(big), FakeResp(grid([]))]
    sess = install(monkeypatch, lr_routes(lambda m, u, p, d: answers.pop(0)))
    rd = CS.LrSearchReader("Beaufort")
    rd.open()
    assert rd.codes == ["LIEN", "LIS/P", "JGMT"] and rd.types == 3
    docs, over = rd.read(date(2025, 1, 1), date(2025, 12, 31))
    assert not over and len(docs) == 1 and docs[0]["fs"] == ["TESTER, ALVIN Q", "TESTER, BERTHA"]
    assert rd.read(date(2025, 1, 1), date(2025, 12, 31)) == ([], True)
    assert rd.read(date(2025, 1, 1), date(2025, 1, 2)) == ([], False)
    posts = [d for m, u, p, d in sess.calls if m == "POST"]
    assert posts[0]["IsAdvancedSearch"] == "True" and posts[0]["DocTypes"] == "LIEN,LIS/P,JGMT"


def test_marriage_reader_summaries_and_overflow(monkeypatch):
    page = grid([marriage_row(0, "09/12/2026", "ROE", "JANE M", "DOE", "RICHARD A", "42", "155", "29257", "09/04/2026")])
    big = grid([marriage_row(0, "09/12/2026", "ROE", "JANE M", "DOE", "RICHARD A", "42", "155", "29257", "09/04/2026")], n=900)
    answers = [FakeResp(page), FakeResp(big), FakeResp(grid([]))]
    sess = install(monkeypatch, [("GET", "VRMarriageSearch/MarriageIndex", FakeResp(MARRIAGE_PAGE)),
                                 ("POST", "VRMarriageSearch/ExecuteSearch", lambda m, u, p, d: answers.pop(0))])
    rd = CS.MarriageReader("Beaufort")
    rd.open()
    docs, over = rd.read(date(2026, 9, 1), date(2026, 9, 30))
    assert not over and docs == [{"t": "MARRIAGE", "d": "2026-09-12", "x": "2026-09-04", "i": "29257", "b": "42", "p": "155",
                                  "fs": ["DOE, RICHARD A"], "gs": ["ROE, JANE M"]}]
    assert rd.read(date(2026, 9, 1), date(2026, 9, 30)) == ([], True)
    assert rd.read(date(2026, 10, 1), date(2026, 10, 9)) == ([], False)
    post = [d for m, u, p, d in sess.calls if m == "POST"][0]
    assert post["fromdate"] == "09/01/2026" and post["todate"] == "09/30/2026" and post["last"] == ""


CCHS_APP = "<html><frame src='realestatesearch.asp'/></html>"
CCHS_SEARCH = ("<html><script>var doctype = new Object(); doctype.name = 'LIEN (LIEN)'; doctype.kind = 'LIEN';"
               " BookTypes[BookTypes.length-1].name = 'RECORDS BOOK';"
               " doctype.name = 'DEED (D)'; doctype.kind = 'D'; BookTypes[BookTypes.length-1].name = 'RECORDS BOOK';"
               " doctype.name = 'LIS PENDENS (LIS/P)'; doctype.kind = 'LIS/P'; BookTypes[BookTypes.length-1].name = 'RECORDS BOOK';"
               " doctype.name = 'RELEASE OF LIEN (RL)'; doctype.kind = 'RL'; BookTypes[BookTypes.length-1].name = 'RECORDS BOOK';"
               " this.lastURL = 'SearchService.asp?cmd=search&'</script></html>")


def cchs_party(da, ki, bk, pg, dn, gl, gf, el, ef):
    return (f"<r><da>{da}</da><ki><![CDATA[{ki}]]></ki><bk>{bk}</bk><pg>{pg}</pg><dn>{dn}</dn><or>{gl}</or><or1>{gf}</or1>"
            f"<ee>{el}</ee><ee1>{ef}</ee1><de></de></r>")


def test_cchs_classic_reader_asks_only_for_adverse_kinds_and_bisects_at_the_cap(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    def service(method, url, params, data):
        q = parse_qs(urlsplit(url).query)
        if q["cmd"][0] == "search":
            n = 5000 if q["fromdate"][0].endswith("2025") and q["todate"][0] == "12/31/2025" else 2
            return FakeResp(f"<SearchResponse><recordcount>{n}</recordcount><doccount>1</doccount></SearchResponse>")
        return FakeResp("<Records>" + cchs_party("03/04/2025", "LIEN", "300", "40", "2025000011", "TESTER", "ALVIN Q",
                                                 "EXAMPLE CREDITOR", "") + "</Records>")
    sess = install(monkeypatch, [("GET", "application.asp", FakeResp(CCHS_APP)), ("GET", "realestatesearch.asp", FakeResp(CCHS_SEARCH)),
                                 ("GET", "SearchService.asp", service)])
    rd = CS.CchsClassicReader("Stanly")
    rd.open()
    assert rd.kinds == ["LIEN", "LIS/P"] and rd.types == 2           # the release and the deed are not asked for
    assert rd.read(date(2025, 1, 1), date(2025, 12, 31)) == ([], True)
    docs, over = rd.read(date(2025, 1, 1), date(2025, 6, 30))
    assert not over and docs[0]["fs"] == ["TESTER ALVIN Q"] and docs[0]["t"] == "LIEN"
    asked = [u for m, u, p, d in sess.calls if "cmd=search" in u]
    assert "instrumenttypes=LIEN%2CLIS%2FP" in asked[0]


class FakeSocket:
    def __init__(self, pages):
        self.pages, self.asked, self.closed = pages, [], False

    def ask(self, q):
        self.asked.append(q)
        return self.pages.pop(0)

    def close(self):
        self.closed = True


def ps_reply(docs, total):
    by_hash = {str(i): d for i, d in enumerate(docs)}
    return {"type": "@kofile/FETCH_DOCUMENTS_FULFILLED/v6",
            "payload": {"meta": {"numRecords": total}, "data": {"byOrder": list(by_hash), "byHash": by_hash}}}


def ps_doc(rec, kind, book, page, g1, g2):
    return {"recordedDate": rec, "docType": kind, "docTypeCode": kind, "volume": book, "page": page,
            "instrumentNumber": f"2025{page:06d}", "grantor": [g1], "grantee": [g2]}


PS_ROOT = ('<html><script>var s={"docTypes":[{"code":"LIEN","description":"LIEN"},{"code":"FEDTAXLN","description":"FEDERAL TAX LIEN"},'
           '{"code":"SAT MORTGAGE","description":"SATISFACTION OF MORTGAGE"},{"code":"DEEDS","description":"DEED"},'
           '{"code":"TAX LIEN","description":"TAX LIENS"},{"code":"LIEN REL","description":"RELEASE OF LIEN"}]}</script></html>')


class FakeHttp:
    def get(self, url, **kw):
        return SimpleNamespace(text=PS_ROOT, status_code=200, url=url)


def test_publicsearch_reader_pages_through_a_window():
    sock = FakeSocket([ps_reply([ps_doc("3/4/2025", "LIEN", "L", 40, "TESTER ALVIN Q", "EXAMPLE CREDITOR")] * 100, 130),
                       ps_reply([ps_doc("3/5/2025", "TAX LIENS", "L", 41, "SAMPLE CORA B", "STATE DEPT")] * 30, 130)])
    rd = CS.PublicSearchReader("oconee", socket=sock, http=FakeHttp())
    rd.open()
    assert rd.codes == ["LIEN", "FEDTAXLN", "TAX LIEN"] and rd.types == 3
    docs, over = rd.read(date(2025, 3, 1), date(2025, 3, 31))
    assert not over and len(docs) == 130 and docs[0]["d"] == "2025-03-04" and docs[-1]["fs"] == ["SAMPLE CORA B"]
    assert sock.asked[0]["docTypes"] == "LIEN,FEDTAXLN,TAX LIEN" and sock.asked[1]["offset"] == "100"
    assert sock.asked[0]["recordedDateRange"] == "20250301,20250331"
    rd.close()
    assert sock.closed


def test_publicsearch_reader_overflows_after_the_page_cap():
    full = ps_reply([ps_doc("3/4/2025", "LIEN", "L", 40, "A B", "C D")] * 100, 99999)
    sock = FakeSocket([full] * 25)
    rd = CS.PublicSearchReader("oconee", socket=sock, http=FakeHttp())
    rd.open()
    assert rd.read(date(2025, 1, 1), date(2025, 12, 31)) == ([], True)
    assert len(sock.asked) == CS.PublicSearchReader.MAX_PAGES


# ------------------------------------------------------------------------------------------------
# the enrichment pass
# ------------------------------------------------------------------------------------------------

def li(state, county, owner, raw=None):
    return SimpleNamespace(state=state, county=county, owner_name=owner, raw=raw if raw is not None else {})


def test_enrichment_stamps_found_none_found_and_leaves_unmatchable(monkeypatch, tmp_path):
    monkeypatch.setattr(CS, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ES, "SWEEP_COUNTIES", {("NC", "Testco"): (ES.Job("lien", lambda: FakeReader([sdoc("2025-03-01", 1)])),)})
    monkeypatch.setenv("FORECLOSURE_COUNTY_SWEEP_SINCE", "2025-01-01")
    rows = [li("NC", "Testco County", "TESTER ALVIN Q"), li("NC", "Testco", "NOBODY HEREIN"), li("NC", "Testco", ""),
            li("NC", "Other", "TESTER ALVIN Q"), li("NC", "Testco", "TESTER, ALVIN Q")]
    stats = asyncio.run(ES.enrich_county_lien_sweep(rows))
    assert rows[0].raw["rod_lien_sweep"]["status"] == "found"
    assert rows[1].raw["rod_lien_sweep"]["status"] == "none_found"
    assert rows[2].raw == {} and rows[3].raw == {}              # no owner / not a swept county: untouched
    assert rows[4].raw["rod_lien_sweep"]["status"] == "found"
    assert stats["targets"] == 3 and stats["lien_found"] == 2 and stats["lien_none_found"] == 1
    assert stats["counties"][0]["window_from"] == "2025-01-01"


def test_enrichment_walled_county_stamps_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(CS, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ES, "SWEEP_COUNTIES", {("NC", "Testco"): (ES.Job("lien", lambda: FakeReader([], fail_at=1)),)})
    rows = [li("NC", "Testco", "TESTER ALVIN Q")]
    stats = asyncio.run(ES.enrich_county_lien_sweep(rows))
    assert rows[0].raw == {} and stats["not_stamped"] == 1 and stats["counties"][0]["walled"] == "challenge page"


def test_enrichment_marriage_never_overwrites_a_found_licence(monkeypatch, tmp_path):
    class MarriageFake(FakeReader):
        def read(self, a, b):
            return ([], False)
    monkeypatch.setattr(CS, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ES, "SWEEP_COUNTIES", {("NC", "Testco"): (ES.Job("marriage", lambda: MarriageFake([])),)})
    have = {"marriage_license": {"spouse_name": "Jane Roe", "license_date": "2024-02-02"}}
    rows = [li("NC", "Testco", "DOE RICHARD A", dict(have)), li("NC", "Testco", "ROE JANE M")]
    asyncio.run(ES.enrich_county_lien_sweep(rows))
    assert rows[0].raw["marriage_license"]["spouse_name"] == "Jane Roe"
    assert rows[1].raw["marriage_license"]["status"] == "no_match" and rows[1].raw["marriage_license"]["checked_at"]


def test_enrichment_flags(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_COUNTY_LIEN_SWEEP", "0")
    assert "disabled" in asyncio.run(ES.enrich_county_lien_sweep([li("NC", "Orange", "TESTER ALVIN Q")]))["skipped"]
    monkeypatch.setenv("FORECLOSURE_COUNTY_LIEN_SWEEP", "1")
    assert "no listing" in asyncio.run(ES.enrich_county_lien_sweep([li("NC", "Wake", "TESTER ALVIN Q")]))["skipped"]


def test_registry_names_every_county_and_its_readers():
    nc = {"Orange", "Stanly", "Surry", "Beaufort", *CS.HOSTED_CCHS}
    assert set(ES.SWEEP_COUNTIES) == {("NC", c) for c in nc} | {("SC", "Sumter"), ("SC", "Oconee")}
    assert [j.kind for j in ES.SWEEP_COUNTIES[("NC", "Beaufort")]] == ["lien", "marriage"]
    assert {"Gates", "Hertford", "Franklin", "Caldwell", "Currituck", "Chowan", "Hyde", "Montgomery", "Caswell",
            "Camden"} <= set(CS.HOSTED_CCHS)


def test_hosted_cchs_reader_never_asks_for_the_frame_page(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    def service(method, url, params, data):
        q = parse_qs(urlsplit(url).query)
        if q["cmd"][0] == "search":
            return FakeResp("<SearchResponse><recordcount>1</recordcount><doccount>1</doccount></SearchResponse>")
        return FakeResp("<Records>" + cchs_party("03/04/2025", "LIEN", "300", "40", "2025000011", "TESTER", "ALVIN Q",
                                                 "EXAMPLE CREDITOR", "") + "</Records>")
    sess = install(monkeypatch, [("GET", "realestatesearch.asp", FakeResp(CCHS_SEARCH)), ("GET", "SearchService.asp", service)])
    rd = CS.CchsClassicReader("Hertford")
    rd.open()
    docs, over = rd.read(date(2025, 1, 1), date(2025, 6, 30))
    assert not over and docs[0]["fs"] == ["TESTER ALVIN Q"]
    urls = [u for m, u, p, d in sess.calls]
    assert not any("application.asp" in u for u in urls)            # the Cloudflare-fronted frame page is never fetched
    assert all(u.startswith("https://us4.courthousecomputersystems.com/HertfordNCNW/") for u in urls)


def test_hosted_cchs_cloudflare_challenge_walls_the_county_and_stops(monkeypatch, tmp_path):
    sess = install(monkeypatch, [("GET", "realestatesearch.asp", FakeResp(CCHS_SEARCH)), ("GET", "SearchService.asp", CLOUDFLARE_403)])
    idx, res = CS.sweep(CS.CchsClassicReader("Gates"), since=date(2025, 1, 1), today=date(2025, 12, 31), cache_dir=tmp_path)
    assert res.walled and res.window_from is None
    n = len(sess.calls)
    idx, res = CS.sweep(CS.CchsClassicReader("Gates"), since=date(2025, 1, 1), today=date(2025, 12, 31), cache_dir=tmp_path)
    assert res.walled and len(sess.calls) == n                      # a walled county gets no further request


# ------------------------------------------------------------------------------------------------
# Cloudflare's passive beacon is not a challenge; a real challenge still is
# ------------------------------------------------------------------------------------------------

BEACON_PAGE = ("<html><head><title>Register Of Deeds | Testco County, NC</title></head><body>search form here"
               "<script>var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';"
               "document.head.appendChild(a);</script></body></html>")


def test_shared_wall_detector_reads_the_passive_beacon_as_a_challenge():
    assert nc_polite.wall_reason(200, "https://us5.example/Tenant/", BEACON_PAGE) == "challenge page"


def test_beacon_blind_client_passes_a_beacon_only_page(monkeypatch):
    install(monkeypatch, [("GET", "realestatesearch.asp", FakeResp(BEACON_PAGE))])
    c = CS.beacon_blind_client("t", "NC", "Testco")
    assert "search form here" in c.get("https://us5.example/Tenant/realestatesearch.asp").text


def test_beacon_blind_client_still_walls_real_challenges(monkeypatch):
    jam = FakeResp("<html><head><title>Just a moment...</title></head><body>" + BEACON_PAGE + "</body></html>", 200)
    for county, answer in (("A", jam), ("B", CLOUDFLARE_403), ("C", CAPTCHA_PAGE),
                           ("D", FakeResp(BEACON_PAGE.replace("</body>", "<div class='g-recaptcha'></div></body>"), 200))):
        install(monkeypatch, [("GET", "x.asp", answer)])
        c = CS.beacon_blind_client("t", "NC", county)
        with pytest.raises(nc_polite.RodWalled):
            c.get("https://us5.example/Tenant/x.asp")
        assert nc_polite.walled_reason("t", "NC", county)


# ------------------------------------------------------------------------------------------------
# the invariants (scripts/audit_checks/top80_register_cchs_kofile.py)
# ------------------------------------------------------------------------------------------------

def _invariants():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "top80_register_cchs_kofile.py"
    spec = importlib.util.spec_from_file_location("top80_register_cchs_kofile", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _stamp(**kw):
    base = {"platform": "govos_countyfusion_sweep", "status": "none_found", "checked_at": "2026-10-09",
            "window_from": "2016-01-01", "window_to": "2026-10-09", "instruments": [], "adverse_count": 0,
            "possible_count": 0}
    base.update(kw)
    return base


def _run(checks, rows):
    for r in rows:
        for c in checks:
            c.feed(r)
    return {c.name: c.finish() for c in checks}


def test_invariant_stamp_shape_catches_a_negative_without_its_window_and_a_found_without_an_exact_hit():
    m = _invariants()
    row = lambda s: {"state": "SC", "county": "Sumter", "owner_name": "X", "raw": {"rod_lien_sweep": s}}  # noqa: E731
    good = _run(m.make_checks(), [row(_stamp()), row(_stamp(status="found", adverse_count=1,
                                                            instruments=[{"fit": "exact"}]))])
    assert good["top80-sweep-stamp-shape"]["ok"] and good["top80-sweep-stamp-shape"]["checked"] == 2
    for bad in (_stamp(window_from=None), _stamp(instruments=[{"fit": "name"}]), _stamp(status="found"),
                _stamp(status="found", adverse_count=1, instruments=[{"fit": "name"}]), _stamp(checked_at=None),
                _stamp(window_from="2027-01-01")):
        out = _run(m.make_checks(), [row(bad)])["top80-sweep-stamp-shape"]
        assert not out["ok"] and out["violations"] == 1, bad
    other = _run(m.make_checks(), [row(_stamp(platform="harris_acclaimweb_lien_sweep", window_from=None))])
    assert other["top80-sweep-stamp-shape"]["checked"] == 0            # another group's stamps are not judged here


def test_invariant_county_silent_waits_for_the_first_sweep_then_demands_every_county():
    m = _invariants()
    owners = [{"state": "SC", "county": "Sumter", "owner_name": f"OWNER {i}", "raw": {}} for i in range(25)]
    assert _run(m.make_checks(), owners)["top80-sweep-county-silent"]["detail"].startswith("not run yet")
    stamped = {"state": "NC", "county": "Orange", "owner_name": "A B", "raw": {"rod_lien_sweep": _stamp(platform="ccs_classic_asp_sweep")}}
    orange = [{"state": "NC", "county": "Orange", "owner_name": f"OWNER {i}", "raw": {}} for i in range(25)]
    out = _run(m.make_checks(), owners + orange + [stamped])["top80-sweep-county-silent"]
    assert not out["ok"] and "SC Sumter" in out["detail"] and "NC Orange" not in out["detail"].split("none stamped:")[1].split(";")[0]


def test_invariant_marriage_shape():
    m = _invariants()
    row = lambda s: {"state": "NC", "county": "Beaufort", "owner_name": "X", "raw": {"marriage_license": s}}  # noqa: E731
    base = {"source": "ccs_lrsearch_marriage_sweep", "checked_at": "2026-10-09", "window_from": "2016-01-01", "window_to": "2026-10-09"}
    ok = _run(m.make_checks(), [row({**base, "status": "no_match"}),
                                row({**base, "status": "found", "spouse_name": "Jane Roe", "license_date": "2026-09-04"})])
    assert ok["top80-marriage-sweep-shape"]["ok"] and ok["top80-marriage-sweep-shape"]["checked"] == 2
    for bad in ({**base, "status": "no_match", "window_from": None}, {**base, "status": "found"}):
        assert not _run(m.make_checks(), [row(bad)])["top80-marriage-sweep-shape"]["ok"]
